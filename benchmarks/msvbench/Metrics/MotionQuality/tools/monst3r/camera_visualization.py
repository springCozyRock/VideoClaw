"""Quaternion utility matching the native MSVBench caller's wxyz convention."""
from scipy.spatial.transform import Rotation

def quaternion_to_euler(qw,qx,qy,qz):
 return tuple(Rotation.from_quat([qx,qy,qz,qw]).as_euler('xyz',degrees=False))
