from collections import OrderedDict

import numpy as np
import torch
import torch.nn as nn

from .darknet import darknet53
from .backbone import Backbone, Multi_Concat_Block, Conv, SiLU, Transition_Block, autopad


def conv2d(filter_in, filter_out, kernel_size):
    pad = (kernel_size - 1) // 2 if kernel_size else 0
    return nn.Sequential(OrderedDict([
        ("conv", nn.Conv2d(filter_in, filter_out, kernel_size=kernel_size, stride=1, padding=pad, bias=False)),
        ("bn", nn.BatchNorm2d(filter_out)),
        ("relu", nn.LeakyReLU(0.1)),
    ]))


def make_last_layers(filters_list, in_filters, out_filter):
    m = nn.Sequential(
        conv2d(in_filters, filters_list[0], 1),
        conv2d(filters_list[0], filters_list[1], 3),
        conv2d(filters_list[1], filters_list[0], 1),
        conv2d(filters_list[0], filters_list[1], 3),
        conv2d(filters_list[1], filters_list[0], 1),
        conv2d(filters_list[0], filters_list[1], 3),
        nn.Conv2d(filters_list[1], out_filter, kernel_size=1, stride=1, padding=0, bias=True)
    )
    return m


class Yolov3Body(nn.Module):
    def __init__(self, anchors_mask, num_classes, pretrained = False):
        super().__init__()
        self.backbone = darknet53()
        if pretrained:
            self.backbone.load_state_dict(torch.load("/home/stat-zx/TCTdet/netyolo/yolov3_darknet53.pth"))

        out_filters = self.backbone.layers_out_filters
        self.last_layer0            = make_last_layers([512, 1024], out_filters[-1], len(anchors_mask[0]) * (num_classes + 4))

        self.last_layer1_conv       = conv2d(512, 256, 1)
        self.last_layer1_upsample   = nn.Upsample(scale_factor=2, mode='nearest')
        self.last_layer1            = make_last_layers([256, 512], out_filters[-2] + 256, len(anchors_mask[1]) * (num_classes + 4))

        self.last_layer2_conv       = conv2d(256, 128, 1)
        self.last_layer2_upsample   = nn.Upsample(scale_factor=2, mode='nearest')
        self.last_layer2            = make_last_layers([128, 256], out_filters[-3] + 128, len(anchors_mask[2]) * (num_classes + 4))

    def forward(self, x):
        x2, x1, x0 = self.backbone(x)
        out0_branch = self.last_layer0[:5](x0)
        out0        = self.last_layer0[5:](out0_branch)

        x1_in = self.last_layer1_conv(out0_branch)
        x1_in = self.last_layer1_upsample(x1_in)
        x1_in = torch.cat([x1_in, x1], 1)
        out1_branch = self.last_layer1[:5](x1_in)
        out1        = self.last_layer1[5:](out1_branch)

        x2_in = self.last_layer2_conv(out1_branch)
        x2_in = self.last_layer2_upsample(x2_in)
        x2_in = torch.cat([x2_in, x2], 1)
        out2 = self.last_layer2(x2_in)
        return out0, out1, out2
    


class SPPCSPC(nn.Module):
    def __init__(self, c1, c2, n=1, shortcut=False, g=1, e=0.5, k=(5, 9, 13)):
        super(SPPCSPC, self).__init__()
        c_ = int(2 * c2 * e)  # hidden channels
        self.cv1 = Conv(c1, c_, 1, 1)
        self.cv2 = Conv(c1, c_, 1, 1)
        self.cv3 = Conv(c_, c_, 3, 1)
        self.cv4 = Conv(c_, c_, 1, 1)
        self.m = nn.ModuleList([nn.MaxPool2d(kernel_size=x, stride=1, padding=x // 2) for x in k])
        self.cv5 = Conv(4 * c_, c_, 1, 1)
        self.cv6 = Conv(c_, c_, 3, 1)
        self.cv7 = Conv(2 * c_, c2, 1, 1)

    def forward(self, x):
        x1 = self.cv4(self.cv3(self.cv1(x)))
        y1 = self.cv6(self.cv5(torch.cat([x1] + [m(x1) for m in self.m], 1)))
        y2 = self.cv2(x)
        return self.cv7(torch.cat((y1, y2), dim=1))


class RepConv(nn.Module):
    def __init__(self, c1, c2, k=3, s=1, p=None, g=1, act=SiLU(), deploy=False):
        super(RepConv, self).__init__()
        self.deploy         = deploy
        self.groups         = g
        self.in_channels    = c1
        self.out_channels   = c2
        
        assert k == 3
        assert autopad(k, p) == 1

        padding_11  = autopad(k, p) - k // 2
        self.act    = nn.LeakyReLU(0.1, inplace=True) if act is True else (act if isinstance(act, nn.Module) else nn.Identity())

        if deploy:
            self.rbr_reparam    = nn.Conv2d(c1, c2, k, s, autopad(k, p), groups=g, bias=True)
        else:
            self.rbr_identity   = (nn.BatchNorm2d(num_features=c1, eps=0.001, momentum=0.03) if c2 == c1 and s == 1 else None)
            self.rbr_dense      = nn.Sequential(
                nn.Conv2d(c1, c2, k, s, autopad(k, p), groups=g, bias=False),
                nn.BatchNorm2d(num_features=c2, eps=0.001, momentum=0.03),
            )
            self.rbr_1x1        = nn.Sequential(
                nn.Conv2d( c1, c2, 1, s, padding_11, groups=g, bias=False),
                nn.BatchNorm2d(num_features=c2, eps=0.001, momentum=0.03),
            )

    def forward(self, inputs):
        if hasattr(self, "rbr_reparam"):
            return self.act(self.rbr_reparam(inputs))
        if self.rbr_identity is None:
            id_out = 0
        else:
            id_out = self.rbr_identity(inputs)
        return self.act(self.rbr_dense(inputs) + self.rbr_1x1(inputs) + id_out)
    
    def get_equivalent_kernel_bias(self):
        kernel3x3, bias3x3  = self._fuse_bn_tensor(self.rbr_dense)
        kernel1x1, bias1x1  = self._fuse_bn_tensor(self.rbr_1x1)
        kernelid, biasid    = self._fuse_bn_tensor(self.rbr_identity)
        return (
            kernel3x3 + self._pad_1x1_to_3x3_tensor(kernel1x1) + kernelid,
            bias3x3 + bias1x1 + biasid,
        )

    def _pad_1x1_to_3x3_tensor(self, kernel1x1):
        if kernel1x1 is None:
            return 0
        else:
            return nn.functional.pad(kernel1x1, [1, 1, 1, 1])

    def _fuse_bn_tensor(self, branch):
        if branch is None:
            return 0, 0
        if isinstance(branch, nn.Sequential):
            kernel      = branch[0].weight
            running_mean = branch[1].running_mean
            running_var = branch[1].running_var
            gamma       = branch[1].weight
            beta        = branch[1].bias
            eps         = branch[1].eps
        else:
            assert isinstance(branch, nn.BatchNorm2d)
            if not hasattr(self, "id_tensor"):
                input_dim = self.in_channels // self.groups
                kernel_value = np.zeros(
                    (self.in_channels, input_dim, 3, 3), dtype=np.float32
                )
                for i in range(self.in_channels):
                    kernel_value[i, i % input_dim, 1, 1] = 1
                self.id_tensor = torch.from_numpy(kernel_value).to(branch.weight.device)
            kernel      = self.id_tensor
            running_mean = branch.running_mean
            running_var = branch.running_var
            gamma       = branch.weight
            beta        = branch.bias
            eps         = branch.eps
        std = (running_var + eps).sqrt()
        t   = (gamma / std).reshape(-1, 1, 1, 1)
        return kernel * t, beta - running_mean * gamma / std

    def repvgg_convert(self):
        kernel, bias = self.get_equivalent_kernel_bias()
        return (
            kernel.detach().cpu().numpy(),
            bias.detach().cpu().numpy(),
        )

    def fuse_conv_bn(self, conv, bn):
        std     = (bn.running_var + bn.eps).sqrt()
        bias    = bn.bias - bn.running_mean * bn.weight / std

        t       = (bn.weight / std).reshape(-1, 1, 1, 1)
        weights = conv.weight * t

        bn      = nn.Identity()
        conv    = nn.Conv2d(in_channels = conv.in_channels,
                              out_channels = conv.out_channels,
                              kernel_size = conv.kernel_size,
                              stride=conv.stride,
                              padding = conv.padding,
                              dilation = conv.dilation,
                              groups = conv.groups,
                              bias = True,
                              padding_mode = conv.padding_mode)

        conv.weight = torch.nn.Parameter(weights)
        conv.bias   = torch.nn.Parameter(bias)
        return conv

    def fuse_repvgg_block(self):    
        if self.deploy:
            return
        print(f"RepConv.fuse_repvgg_block")
        self.rbr_dense  = self.fuse_conv_bn(self.rbr_dense[0], self.rbr_dense[1])
        
        self.rbr_1x1    = self.fuse_conv_bn(self.rbr_1x1[0], self.rbr_1x1[1])
        rbr_1x1_bias    = self.rbr_1x1.bias
        weight_1x1_expanded = torch.nn.functional.pad(self.rbr_1x1.weight, [1, 1, 1, 1])
        
        # Fuse self.rbr_identity
        if (isinstance(self.rbr_identity, nn.BatchNorm2d) or isinstance(self.rbr_identity, nn.modules.batchnorm.SyncBatchNorm)):
            identity_conv_1x1 = nn.Conv2d(
                    in_channels=self.in_channels,
                    out_channels=self.out_channels,
                    kernel_size=1,
                    stride=1,
                    padding=0,
                    groups=self.groups, 
                    bias=False)
            identity_conv_1x1.weight.data = identity_conv_1x1.weight.data.to(self.rbr_1x1.weight.data.device)
            identity_conv_1x1.weight.data = identity_conv_1x1.weight.data.squeeze().squeeze()
            identity_conv_1x1.weight.data.fill_(0.0)
            identity_conv_1x1.weight.data.fill_diagonal_(1.0)
            identity_conv_1x1.weight.data = identity_conv_1x1.weight.data.unsqueeze(2).unsqueeze(3)

            identity_conv_1x1           = self.fuse_conv_bn(identity_conv_1x1, self.rbr_identity)
            bias_identity_expanded      = identity_conv_1x1.bias
            weight_identity_expanded    = torch.nn.functional.pad(identity_conv_1x1.weight, [1, 1, 1, 1])            
        else:
            bias_identity_expanded      = torch.nn.Parameter( torch.zeros_like(rbr_1x1_bias) )
            weight_identity_expanded    = torch.nn.Parameter( torch.zeros_like(weight_1x1_expanded) )            
        
        self.rbr_dense.weight   = torch.nn.Parameter(self.rbr_dense.weight + weight_1x1_expanded + weight_identity_expanded)
        self.rbr_dense.bias     = torch.nn.Parameter(self.rbr_dense.bias + rbr_1x1_bias + bias_identity_expanded)
                
        self.rbr_reparam    = self.rbr_dense
        self.deploy         = True

        if self.rbr_identity is not None:
            del self.rbr_identity
            self.rbr_identity = None

        if self.rbr_1x1 is not None:
            del self.rbr_1x1
            self.rbr_1x1 = None

        if self.rbr_dense is not None:
            del self.rbr_dense
            self.rbr_dense = None
            
def fuse_conv_and_bn(conv, bn):
    fusedconv = nn.Conv2d(conv.in_channels,
                          conv.out_channels,
                          kernel_size=conv.kernel_size,
                          stride=conv.stride,
                          padding=conv.padding,
                          groups=conv.groups,
                          bias=True).requires_grad_(False).to(conv.weight.device)

    w_conv  = conv.weight.clone().view(conv.out_channels, -1)
    w_bn    = torch.diag(bn.weight.div(torch.sqrt(bn.eps + bn.running_var)))
    # fusedconv.weight.copy_(torch.mm(w_bn, w_conv).view(fusedconv.weight.shape))
    fusedconv.weight.copy_(torch.mm(w_bn, w_conv).view(fusedconv.weight.shape).detach())

    b_conv  = torch.zeros(conv.weight.size(0), device=conv.weight.device) if conv.bias is None else conv.bias
    b_bn    = bn.bias - bn.weight.mul(bn.running_mean).div(torch.sqrt(bn.running_var + bn.eps))
    # fusedconv.bias.copy_(torch.mm(w_bn, b_conv.reshape(-1, 1)).reshape(-1) + b_bn)
    fusedconv.bias.copy_((torch.mm(w_bn, b_conv.reshape(-1, 1)).reshape(-1) + b_bn).detach())
    return fusedconv


class Yolov7Body(nn.Module):
    def __init__(self, anchors_mask, num_classes, pretrained=False):
        super().__init__()

        transition_channels = 32
        block_channels      = 32
        panet_channels      = 32
        e       = 2
        n       = 4
        ids     = [-1, -2, -3, -4, -5, -6]
        conv    = RepConv
        self.backbone   = Backbone(transition_channels, block_channels, n)
        if pretrained:
            self.backbone.load_state_dict(torch.load("/home/stat-zx/TCTdet/netyolo/yolov7_backbone_weights.pth"))
        self.upsample   = nn.Upsample(scale_factor=2, mode="nearest")

        # 20, 20, 1024 => 20, 20, 512
        self.sppcspc                = SPPCSPC(transition_channels * 32, transition_channels * 16)
        # 20, 20, 512 => 20, 20, 256 => 40, 40, 256
        self.conv_for_P5            = Conv(transition_channels * 16, transition_channels * 8)
        # 40, 40, 1024 => 40, 40, 256
        self.conv_for_feat2         = Conv(transition_channels * 32, transition_channels * 8)
        # 40, 40, 512 => 40, 40, 256
        self.conv3_for_upsample1    = Multi_Concat_Block(transition_channels * 16, panet_channels * 4, transition_channels * 8, e=e, n=n, ids=ids)

        # 40, 40, 256 => 40, 40, 128 => 80, 80, 128
        self.conv_for_P4            = Conv(transition_channels * 8, transition_channels * 4)
        # 80, 80, 512 => 80, 80, 128
        self.conv_for_feat1         = Conv(transition_channels * 16, transition_channels * 4)
        # 80, 80, 256 => 80, 80, 128
        self.conv3_for_upsample2    = Multi_Concat_Block(transition_channels * 8, panet_channels * 2, transition_channels * 4, e=e, n=n, ids=ids)

        # 80, 80, 128 => 40, 40, 256
        self.down_sample1           = Transition_Block(transition_channels * 4, transition_channels * 4)
        # 40, 40, 512 => 40, 40, 256
        self.conv3_for_downsample1  = Multi_Concat_Block(transition_channels * 16, panet_channels * 4, transition_channels * 8, e=e, n=n, ids=ids)

        # 40, 40, 256 => 20, 20, 512
        self.down_sample2           = Transition_Block(transition_channels * 8, transition_channels * 8)
        # 20, 20, 1024 => 20, 20, 512
        self.conv3_for_downsample2  = Multi_Concat_Block(transition_channels * 32, panet_channels * 8, transition_channels * 16, e=e, n=n, ids=ids)

        # 80, 80, 128 => 80, 80, 256
        self.rep_conv_1 = conv(transition_channels * 4, transition_channels * 8, 3, 1)
        # 40, 40, 256 => 40, 40, 512
        self.rep_conv_2 = conv(transition_channels * 8, transition_channels * 16, 3, 1)
        # 20, 20, 512 => 20, 20, 1024
        self.rep_conv_3 = conv(transition_channels * 16, transition_channels * 32, 3, 1)

        # 80, 80, 256 => 80, 80, 3 * 25 (4 + 1 + 20) & 85 (4 + 1 + 80)
        self.yolo_head_P3 = nn.Conv2d(transition_channels * 8, len(anchors_mask[2]) * (4 + num_classes), 1)
        # 40, 40, 512 => 40, 40, 3 * 25 & 85
        self.yolo_head_P4 = nn.Conv2d(transition_channels * 16, len(anchors_mask[1]) * (4 + num_classes), 1)
        # 20, 20, 512 => 20, 20, 3 * 25 & 85
        self.yolo_head_P5 = nn.Conv2d(transition_channels * 32, len(anchors_mask[0]) * (4 + num_classes), 1)

    def fuse(self):
        print('Fusing layers... ')
        for m in self.modules():
            if isinstance(m, RepConv):
                m.fuse_repvgg_block()
            elif type(m) is Conv and hasattr(m, 'bn'):
                m.conv = fuse_conv_and_bn(m.conv, m.bn)
                delattr(m, 'bn')
                m.forward = m.fuseforward
        return self
    
    def forward(self, x):
        #  backbone
        feat1, feat2, feat3 = self.backbone.forward(x)
        
        P5 = self.sppcspc(feat3)
        P5_conv = self.conv_for_P5(P5)
        P5_upsample = self.upsample(P5_conv)
        
        P4 = torch.cat([self.conv_for_feat2(feat2), P5_upsample], 1)
        P4 = self.conv3_for_upsample1(P4)
        P4_conv = self.conv_for_P4(P4)
        P4_upsample = self.upsample(P4_conv)
        
        P3 = torch.cat([self.conv_for_feat1(feat1), P4_upsample], 1)
        P3 = self.conv3_for_upsample2(P3)
        P3_downsample = self.down_sample1(P3)
        
        P4 = torch.cat([P3_downsample, P4], 1)
        P4 = self.conv3_for_downsample1(P4)
        P4_downsample = self.down_sample2(P4)
        
        P5 = torch.cat([P4_downsample, P5], 1)
        P5 = self.conv3_for_downsample2(P5)
        
        P3 = self.rep_conv_1(P3)
        P4 = self.rep_conv_2(P4)
        P5 = self.rep_conv_3(P5)
        out2 = self.yolo_head_P3(P3)
        out1 = self.yolo_head_P4(P4)
        out0 = self.yolo_head_P5(P5)

        return [out0, out1, out2]