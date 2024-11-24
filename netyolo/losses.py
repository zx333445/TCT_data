import torch
import torch.nn as nn
import numpy as np
import math


def bbox_iou(box1, box2, x1y1x2y2=True):
    """
    Returns the IoU of two bounding boxes
    """
    if not x1y1x2y2:
        # Transform from center and width to exact coordinates
        b1_x1, b1_x2 = box1[:, 0] - box1[:, 2] / 2, box1[:, 0] + box1[:, 2] / 2
        b1_y1, b1_y2 = box1[:, 1] - box1[:, 3] / 2, box1[:, 1] + box1[:, 3] / 2
        b2_x1, b2_x2 = box2[:, 0] - box2[:, 2] / 2, box2[:, 0] + box2[:, 2] / 2
        b2_y1, b2_y2 = box2[:, 1] - box2[:, 3] / 2, box2[:, 1] + box2[:, 3] / 2
    else:
        # Get the coordinates of bounding boxes
        b1_x1, b1_y1, b1_x2, b1_y2 = box1[:,0], box1[:,1], box1[:,2], box1[:,3]
        b2_x1, b2_y1, b2_x2, b2_y2 = box2[:,0], box2[:,1], box2[:,2], box2[:,3]

    # get the corrdinates of the intersection rectangle
    inter_rect_x1 =  torch.max(b1_x1, b2_x1)
    inter_rect_y1 =  torch.max(b1_y1, b2_y1)
    inter_rect_x2 =  torch.min(b1_x2, b2_x2)
    inter_rect_y2 =  torch.min(b1_y2, b2_y2)
    # Intersection area
    inter_area =    torch.clamp(inter_rect_x2 - inter_rect_x1 + 1, min=0) * \
                    torch.clamp(inter_rect_y2 - inter_rect_y1 + 1, min=0)
    # Union Area
    b1_area = (b1_x2 - b1_x1 + 1) * (b1_y2 - b1_y1 + 1)
    b2_area = (b2_x2 - b2_x1 + 1) * (b2_y2 - b2_y1 + 1)

    iou = inter_area / (b1_area + b2_area - inter_area + 1e-16)

    return iou


class YOLOLoss(nn.Module):
    def __init__(self, num_classes, input_size, anchors):
        super(YOLOLoss, self).__init__()
        self.num_classes = num_classes
        self.input_size = input_size
        self.anchors = anchors
        self.num_anchors = len(anchors)
        self.bbox_attrs = 4 + self.num_classes

        self.ignore_threshold = 0.5
        self.lambda_xy = 2.5
        self.lambda_wh = 2.5
        self.lambda_obj = 1.0
        self.lambda_cls = 1.0

        self.mse_loss = nn.MSELoss()
        self.bce_loss = nn.BCELoss()

    def forward(self, input, targets):
        device = input.device
        bs = input.size(0)
        in_h = input.size(2)
        in_w = input.size(3)
        stride_h = self.input_size[0] / in_h
        stride_w = self.input_size[1] / in_w
        scaled_anchors = [(a_w / stride_w, a_h / stride_h) for a_w, a_h in self.anchors]

        prediction = input.view(bs,  self.num_anchors,
                                self.bbox_attrs, in_h, in_w).permute(0, 1, 3, 4, 2).contiguous()

        # Get outputs
        x = torch.sigmoid(prediction[..., 0])          # Center x
        y = torch.sigmoid(prediction[..., 1])          # Center y
        w = prediction[..., 2]                         # Width
        h = prediction[..., 3]                         # Height
        conf = torch.sigmoid(prediction[..., 4])       # Conf
        pred_cls = torch.sigmoid(prediction[..., 5:])  # Cls pred.

        if self.training:
            #  build target
            mask, noobj_mask, tx, ty, tw, th, tconf, tcls = self.get_target(targets, scaled_anchors,
                                                                           in_w, in_h,
                                                                           self.ignore_threshold)
            mask, noobj_mask = mask.to(device), noobj_mask.to(device)
            tx, ty, tw, th = tx.to(device), ty.to(device), tw.to(device), th.to(device)
            tconf, tcls = tconf.to(device), tcls.to(device)
            #  losses.
            loss_x = self.bce_loss(x * mask, tx * mask) * self.lambda_xy
            loss_y = self.bce_loss(y * mask, ty * mask) * self.lambda_xy
            loss_w = self.mse_loss(w * mask, tw * mask) * self.lambda_wh
            loss_h = self.mse_loss(h * mask, th * mask) * self.lambda_wh
            loss_obj = (self.bce_loss(conf * mask, mask) + \
                0.5 * self.bce_loss(conf * noobj_mask, noobj_mask * 0.0)) * self.lambda_obj
            loss_cls = self.bce_loss(pred_cls[mask == 1], tcls[mask == 1]) * self.lambda_cls

            return [loss_x, loss_y, loss_w, loss_h, loss_obj, loss_cls]
        else:
            # Calculate offsets for each grid
            grid_x = torch.tensor(np.linspace(0, in_w-1, in_w), dtype=torch.float32, device=device) \
                .repeat(in_w, 1).repeat(bs * self.num_anchors, 1, 1).view(x.shape)
            grid_y = torch.tensor(np.linspace(0, in_h-1, in_h), dtype=torch.float32, device=device) \
                .repeat(in_h, 1).t().repeat(bs * self.num_anchors, 1, 1).view(y.shape)
            # Calculate anchor w, h
            anchor_w = torch.tensor(scaled_anchors, dtype=torch.float32, device=device) \
                .index_select(1, torch.tensor([0], dtype=torch.int64, device=device))
            anchor_h = torch.tensor(scaled_anchors, dtype=torch.float32, device=device) \
                .index_select(1, torch.tensor([1], dtype=torch.int64, device=device))
            anchor_w = anchor_w.repeat(bs, 1).repeat(1, 1, in_h * in_w).view(w.shape)
            anchor_h = anchor_h.repeat(bs, 1).repeat(1, 1, in_h * in_w).view(h.shape)
            # Add offset and scale with anchors
            pred_boxes = torch.zeros(prediction[..., :4].shape, dtype=torch.float32, device=device)
            pred_boxes[..., 0] = x + grid_x
            pred_boxes[..., 1] = y + grid_y
            pred_boxes[..., 2] = torch.exp(w) * anchor_w
            pred_boxes[..., 3] = torch.exp(h) * anchor_h
            # Results
            _scale = torch.tensor([stride_w, stride_h] * 2, dtype=torch.float32, device=device)
            output = torch.cat((pred_boxes.view(bs, -1, 4) * _scale,
                                conf.view(bs, -1, 1), pred_cls.view(bs, -1, self.num_classes - 1)), -1)
            return output

    def get_target(self, target, anchors, in_w, in_h, ignore_threshold):
        bs = target.size(0)

        mask = torch.zeros(bs, self.num_anchors, in_h, in_w)
        noobj_mask = torch.ones(bs, self.num_anchors, in_h, in_w)
        tx = torch.zeros(bs, self.num_anchors, in_h, in_w)
        ty = torch.zeros(bs, self.num_anchors, in_h, in_w)
        tw = torch.zeros(bs, self.num_anchors, in_h, in_w)
        th = torch.zeros(bs, self.num_anchors, in_h, in_w)
        tconf = torch.zeros(bs, self.num_anchors, in_h, in_w)
        tcls = torch.zeros(bs, self.num_anchors, in_h, in_w, self.num_classes - 1)
        
        for b in range(bs):
            for t in range(target.shape[1]):
                if target[b, t].sum() == 0:
                    continue
                # Convert from position relative to box
                gx = target[b, t, 0] * in_w
                gy = target[b, t, 1] * in_h
                gw = target[b, t, 2] * in_w
                gh = target[b, t, 3] * in_h

                # Get grid box indices
                gi = int(gx)
                gj = int(gy)
                # Get shape of gt box
                gt_box = torch.tensor([0, 0, gw, gh], dtype=torch.float32).unsqueeze(0)
                # Get shape of anchor box
                anchor_shapes = torch.tensor(
                    np.concatenate((np.zeros((self.num_anchors, 2)), np.array(anchors)), 1),
                    dtype=torch.float32)
                # Calculate iou between gt and anchor shapes
                anch_ious = bbox_iou(gt_box, anchor_shapes)
                # Where the overlap is larger than threshold set mask to zero (ignore)
                noobj_mask[b, anch_ious > ignore_threshold, gj, gi] = 0
                # Find the best matching anchor box
                best_n = np.argmax(anch_ious)

                # Masks
                mask[b, best_n, gj, gi] = 1
                # Coordinates
                tx[b, best_n, gj, gi] = gx - gi
                ty[b, best_n, gj, gi] = gy - gj
                # Width and height
                tw[b, best_n, gj, gi] = math.log(gw/anchors[best_n][0] + 1e-16)
                th[b, best_n, gj, gi] = math.log(gh/anchors[best_n][1] + 1e-16)
                # object
                tconf[b, best_n, gj, gi] = 1
                # One-hot encoding of label
                tcls[b, best_n, gj, gi, int(target[b, t, 4])] = 1

        return mask, noobj_mask, tx, ty, tw, th, tconf, tcls