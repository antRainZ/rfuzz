import sysv_ipc
import struct
import time

KEY=12

memory = sysv_ipc.SharedMemory(KEY)
data = memory.read(4)
print(data)
data = struct.unpack('>I',data)

print(hex(data[0]))

data = memory.read(4)
print(data)
data = struct.unpack('>I',data)
print(hex(data[0]))

time.sleep(1000)