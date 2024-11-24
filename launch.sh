#!/bin/bash
TEST_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/test.csv"
MODEL_NAME='resnet50'
NUM_EPOCHS=30


echo "========Fold1========"
LOG="/home/stat-zx/TCTdet/yolo3results/fold1/logs"
SAVE_MODEL_PATH="/home/stat-zx/TCTdet/yolo3results/fold1/f1.pth"
TRAIN_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold1/train.csv"
VAL_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold1/val.csv"
FOLD=1
python train.py \
    --model_name $MODEL_NAME \
    --logdir $LOG \
    --num_epochs $NUM_EPOCHS \
    --save_model_path $SAVE_MODEL_PATH \
    --train_csv_path $TRAIN_CSV_PATH \
    --val_csv_path $VAL_CSV_PATH \
    --test_csv_path $TEST_CSV_PATH \
    --fold $FOLD\
    AdamW


echo "========Fold2========"
LOG="/home/stat-zx/TCTdet/yolo3results/fold2/logs"
SAVE_MODEL_PATH="/home/stat-zx/TCTdet/yolo3results/fold2/f2.pth"
TRAIN_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold2/train.csv"
VAL_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold2/val.csv"
FOLD=2
python train.py \
    --model_name $MODEL_NAME \
    --logdir $LOG \
    --num_epochs $NUM_EPOCHS \
    --save_model_path $SAVE_MODEL_PATH \
    --train_csv_path $TRAIN_CSV_PATH \
    --val_csv_path $VAL_CSV_PATH \
    --test_csv_path $TEST_CSV_PATH \
    --fold $FOLD\
    AdamW


echo "========Fold3========"
LOG="/home/stat-zx/TCTdet/yolo3results/fold3/logs"
SAVE_MODEL_PATH="/home/stat-zx/TCTdet/yolo3results/fold3/f3.pth"
TRAIN_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold3/train.csv"
VAL_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold3/val.csv"
FOLD=3
python train.py \
    --model_name $MODEL_NAME \
    --logdir $LOG \
    --num_epochs $NUM_EPOCHS \
    --save_model_path $SAVE_MODEL_PATH \
    --train_csv_path $TRAIN_CSV_PATH \
    --val_csv_path $VAL_CSV_PATH \
    --test_csv_path $TEST_CSV_PATH \
    --fold $FOLD\
    AdamW


echo "========Fold4========"
LOG="/home/stat-zx/TCTdet/yolo3results/fold4/logs"
SAVE_MODEL_PATH="/home/stat-zx/TCTdet/yolo3results/fold4/f4.pth"
TRAIN_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold4/train.csv"
VAL_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold4/val.csv"
FOLD=4
python train.py \
    --model_name $MODEL_NAME \
    --logdir $LOG \
    --num_epochs $NUM_EPOCHS \
    --save_model_path $SAVE_MODEL_PATH \
    --train_csv_path $TRAIN_CSV_PATH \
    --val_csv_path $VAL_CSV_PATH \
    --test_csv_path $TEST_CSV_PATH \
    --fold $FOLD\
    AdamW


echo "========Fold5========"
LOG="/home/stat-zx/TCTdet/yolo3results/fold5/logs"
SAVE_MODEL_PATH="/home/stat-zx/TCTdet/yolo3results/fold5/f5.pth"
TRAIN_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold5/train.csv"
VAL_CSV_PATH="/home/stat-zx/TCTdet/csvfiles/fold5/val.csv"
FOLD=5
python train.py \
    --model_name $MODEL_NAME \
    --logdir $LOG \
    --num_epochs $NUM_EPOCHS \
    --save_model_path $SAVE_MODEL_PATH \
    --train_csv_path $TRAIN_CSV_PATH \
    --val_csv_path $VAL_CSV_PATH \
    --test_csv_path $TEST_CSV_PATH \
    --fold $FOLD \
    AdamW

echo "Done!"