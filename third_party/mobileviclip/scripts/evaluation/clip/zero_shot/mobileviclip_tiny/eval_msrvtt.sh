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


export CUDA_VISIBLE_DEVICES=3
MASTER_PORT=$((10660 + $RANDOM % 10))
torchrun --nproc_per_node=${NUM_GPUS} \
         --master_port=${MASTER_PORT} \
         tasks_clip/retrieval.py \
         $(dirname $0)/config_msrvtt.py \

#                 txt_r1  txt_r5  txt_r10  txt_r_mean  img_r1  img_r5  img_r10  img_r_mean  r_mean           
# ret_test/        38.2    65.4     74.8       59.47    38.7    64.9     74.2       59.27   59.37                                                                                                               
# ret_test_emb/    38.1    64.8     74.4       59.10    38.5    64.2     73.7       58.80   58.95