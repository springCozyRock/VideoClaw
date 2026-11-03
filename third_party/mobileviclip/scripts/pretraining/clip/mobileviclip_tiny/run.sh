export MASTER_PORT=$((11000 + $RANDOM % 20000))
export OMP_NUM_THREADS=1
echo "PYTHONPATH: ${PYTHONPATH}"
which_python=$(which python)
echo "which python: ${which_python}"
export PYTHONPATH=${PYTHONPATH}:${which_python}
export PYTHONPATH=${PYTHONPATH}:.
echo "PYTHONPATH: ${PYTHONPATH}"

JOB_NAME='mobileviclip_tiny'
OUTPUT_DIR="$(dirname $0)/$JOB_NAME"
LOG_DIR="./logs/${JOB_NAME}"
PARTITION='video'
NNODE=2
NUM_GPUS=8
NUM_CPU=128

MASTER_PORT=$((11660 + $RANDOM % 10))
torchrun --nproc_per_node=${NUM_GPUS} \
         --master_port=${MASTER_PORT} \
         tasks_clip/pretrain.py \
         $(dirname $0)/config.py \
