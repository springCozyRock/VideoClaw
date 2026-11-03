export MASTER_PORT=$((12000 + $RANDOM % 20000))
export OMP_NUM_THREADS=1
echo "PYTHONPATH: ${PYTHONPATH}"
which_python=$(which python)
echo "which python: ${which_python}"
export PYTHONPATH=${PYTHONPATH}:${which_python}
export PYTHONPATH=${PYTHONPATH}:.
echo "PYTHONPATH: ${PYTHONPATH}"

JOB_NAME='zs_msrvtt'
OUTPUT_DIR="$(dirname $0)/$JOB_NAME"
LOG_DIR="./logs/${JOB_NAME}"
PARTITION='video'
NNODE=1
NUM_GPUS=1
NUM_CPU=16

export CUDA_VISIBLE_DEVICES=0
MASTER_PORT=$((10660 + $RANDOM % 10))
torchrun --nproc_per_node=${NUM_GPUS} \
         --master_port=${MASTER_PORT} \
         tasks_clip/retrieval.py \
         $(dirname $0)/config_msrvtt.py \

#                txt_r1  txt_r5  txt_r10  txt_r_mean  img_r1  img_r5  img_r10  img_r_mean  r_mean                                                                                                               
# ret_test/        42.5    66.7     76.5       61.90    42.6    68.0     76.2       62.27   62.08                                                                                                               
# ret_test_emb/    41.3    67.0     76.4       61.57    41.9    66.1     76.1       61.37   61.47