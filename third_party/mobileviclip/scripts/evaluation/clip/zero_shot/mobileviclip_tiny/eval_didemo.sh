export MASTER_PORT=$((12000 + $RANDOM % 20000))
export OMP_NUM_THREADS=1
echo "PYTHONPATH: ${PYTHONPATH}"
which_python=$(which python)
echo "which python: ${which_python}"
export PYTHONPATH=${PYTHONPATH}:${which_python}
export PYTHONPATH=${PYTHONPATH}:.
echo "PYTHONPATH: ${PYTHONPATH}"

JOB_NAME='zs_didemo'
OUTPUT_DIR="$(dirname $0)/$JOB_NAME"
LOG_DIR="./logs/${JOB_NAME}"
PARTITION='video'
NNODE=1
NUM_GPUS=1
NUM_CPU=16

export CUDA_VISIBLE_DEVICES=1
MASTER_PORT=$((11360 + $RANDOM % 10))
torchrun --nproc_per_node=${NUM_GPUS} \
         --master_port=${MASTER_PORT} \
         tasks_clip/retrieval.py \
         $(dirname $0)/config_didemo.py \

#                txt_r1  txt_r5  txt_r10  txt_r_mean  img_r1  img_r5  img_r10  img_r_mean  r_mean                                                                                                               
# ret_test/       37.11   64.91    73.32       58.45   36.66   64.69    74.89       58.74   58.59
# ret_test_emb/   35.87   64.01    72.76       57.55   33.86   62.89    72.87       56.54   57.04