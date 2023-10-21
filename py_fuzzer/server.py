import sysv_ipc
import struct
import time

KEY=12
try:
    memory = sysv_ipc.SharedMemory(KEY)
    print(memory.id)
    sysv_ipc.remove_shared_memory(memory.id)
except Exception as e:
    print(e)

memory = sysv_ipc.SharedMemory(KEY, sysv_ipc.IPC_CREX)
data = struct.pack('>IIHHHH',0x19931993,0,1,0,0,0)
memory.write(data)

time.sleep(1000)