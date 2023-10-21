import os
import sysv_ipc
import struct
import secrets


class NamedPipe:
    '''
    利用管道传送共享内存id, 后续的共享内存是没有的进行同步操作的,可能先需要将测试写入,然后再发送id
    '''
    def __init__(self) -> None:
        tx_fifo_path = '/tmp/fpga/0/tx.fifo'
        rx_fifo_path = '/tmp/fpga/0/rx.fifo'

        # 需要打开对应的文件,与verilator/fpga_queue.cpp#L27 一致
        self.tx_fifo = open(tx_fifo_path, 'rb')
        self.rx_fifo = open(rx_fifo_path, 'wb')

    def destory(self):
        self.tx_fifo.close()
        self.rx_fifo.close()
    
    def push(self,test_in_id,coverage_out_id):
        print("test_in_id:",test_in_id,"coverage_out_id",coverage_out_id)
        data = struct.pack('II', test_in_id, coverage_out_id)
        print("pipe push:",data)
        self.rx_fifo.write(data)

    def pop(self):
        data = self.tx_fifo.read(8)
        integers = struct.unpack('II', data)
        return integers

class SharedMemory:
    def __init__(self,size) -> None:
        self.memory = sysv_ipc.SharedMemory(sysv_ipc.IPC_PRIVATE, sysv_ipc.IPC_CREX,size=size)
        self.len = 0

    def write(self,data):
        print(data)
        self.memory.write(data,self.len)
        self.len += len(data)

    def read(self,byte_count):
        data = self.memory.read(byte_count)
        return data.decode()
    
    def get_id(self):
        return self.memory.id
    
class TestDataGenerate:
    def __init__(self) -> None:
        pass

    def get_input_left(self):
        return 1
    
    def get_test_data(self,size):
        # Generate random bytes using secrets module
        random_bytes = secrets.token_bytes(size)
        # Return the generated random data
        return random_bytes

class Test:
    MagicTestInputHeader= 0x19931993
    MagicCoverageOutputHeader = 0x73537353
    # fuzzer/src/main.rs#L127
    test_buffer_size = 64 * 1024 * 16
    coverage_buffer_size = 64 * 1024 * 16

    def __init__(self,tests_left=1,buffer_id=0,input_size=16) -> None:
        self.test_in_ptr=SharedMemory(Test.test_buffer_size)
        self.coverage_out_ptr=SharedMemory(Test.coverage_buffer_size)
        self.input_size=input_size
        self.buffer_id=buffer_id
        self.tests_left=tests_left
        self.pipe = NamedPipe()
        pass
    
    def write_header(self):
        '''
        server: 使用change_endianess 改变数据的大小端, 采用大端
        格式:
        32位标记头: MagicTestInputHeader
        32位bufferid
        16位tests_left: 表示需要多少次inputs_left
        16位保留数据
        16位保留数据
        16位保留数据
        64位inputs_left: 表示有多少个InputSize大小的测试数据, 内部会转成16位
        InputSize字节数据: 测试数据
        '''
        data = struct.pack('>IIHHHH',Test.MagicTestInputHeader,self.buffer_id,self.tests_left,0,0,0)
        self.test_in_ptr.write(data)
        pass 

    def write_inputs_left(self,inputs_left):
        data = struct.pack('>Q',inputs_left)
        self.test_in_ptr.write(data)

    def write_test_data(self,data):
        self.test_in_ptr.write(data)

    def start_test(self,gen: TestDataGenerate):
        self.write_header()
        for i in range(self.tests_left):
            input_left = gen.get_input_left()
            self.write_inputs_left(input_left)
            for j in range(input_left):
                data = gen.get_test_data(self.input_size)
                self.write_test_data(data)
        self.pipe.push(self.test_in_ptr.get_id(),self.coverage_out_ptr.get_id())

gen = TestDataGenerate()
test = Test()
test.start_test(gen)