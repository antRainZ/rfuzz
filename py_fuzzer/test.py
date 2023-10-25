import os
import sysv_ipc
import struct
import secrets
import time


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
        # print("test_in_id:",test_in_id,"coverage_out_id",coverage_out_id)
        data = struct.pack('II', test_in_id, coverage_out_id)
        # print("pipe push:",data)
        self.rx_fifo.write(data)
        # verilator/fpga_queue.cpp#L59 写完之后要刷新,不然会卡住
        self.rx_fifo.flush()

    def pop(self):
        data = self.tx_fifo.read(8)
        integers = struct.unpack('II', data)
        print(integers)
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
        data = self.memory.read(byte_count,self.len)
        self.len += byte_count
        return data
    
    def get_id(self):
        return self.memory.id
    
    def destory(self):
        self.memory.remove()

    def reset(self):
        self.len = 0

class MemoryCache:
    cache = {}

    def __init__(self) -> None:
        raise "not support"
    
    @staticmethod
    def get_memory(key,size):
        memory = None
        if key in MemoryCache.cache:
            memory = MemoryCache.cache[key]
            memory.reset()
        else:
            memory = SharedMemory(size)
            MemoryCache.cache[key] = memory
        return memory

    @staticmethod
    def destory():
        for item in	MemoryCache.cache.values():
            item.destory()



class TestDataGenerate:
    '''
    产生测试数据
    '''
    def __init__(self) -> None:
        pass

    def get_input_left(self):
        return 1
    
    def get_test_data(self,size):
        # Generate random bytes using secrets module
        random_bytes = secrets.token_bytes(size)
        # Return the generated random data
        return random_bytes
        # data = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".encode('ascii')
        # return data[:size]

class Test:
    '''
    每次测试
    '''

    MagicTestInputHeader= 0x19931993
    MagicCoverageOutputHeader = 0x73537353
    # fuzzer/src/main.rs#L127
    test_buffer_size = 64 * 1024 * 16
    coverage_buffer_size = 64 * 1024 * 16

    def __init__(self,pipe: NamedPipe,tests_left=1,buffer_id=0,input_size=16,coverage_size=6) -> None:
        self.test_in_ptr = MemoryCache.get_memory("test_in_ptr", Test.test_buffer_size)
        self.coverage_out_ptr= MemoryCache.get_memory("coverage_out_ptr",Test.coverage_buffer_size)
        self.input_size=input_size
        self.buffer_id=buffer_id
        self.tests_left=tests_left
        self.coverage_size=coverage_size
        self.pipe = pipe
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
    
    def parse_header(self):
        '''
        协议内容:
        MagicCoverageOutputHeader: 32位
        buffer_id: 32位
        # 然后下面有tests_left组:
        cycles: 16位
        coverage结果: CoverageSize
        '''
        data = self.coverage_out_ptr.read(8)
        # https://github.com/ekiwi/rfuzz/blob/main/verilator/fpga_queue.cpp#L141, L151
        (magic,buffer_id) = struct.unpack(">II",data)
        # print(magic,buffer_id)
        assert(magic == Test.MagicCoverageOutputHeader)

    def result_analyse(self):
        '''
        分析测试结果
        '''
        data = self.pipe.pop()
        self.parse_header()
        for i in range(self.tests_left):
            data = self.coverage_out_ptr.read(2)
            cycles = struct.unpack(">H",data)
            data = self.coverage_out_ptr.read(self.coverage_size)
            print(cycles,data)
            

    def release_memory(self):
        pass
        # self.coverage_out_ptr.destory()
        # self.test_in_ptr.destory()

class FuzzerTest:

    def __init__(self,):
        self.pipe = NamedPipe()

    def start(self,count,gen:TestDataGenerate):
        for i in range(count):
            print("iteration: ",i)
            test = Test(self.pipe)
            test.start_test(gen)
            test.result_analyse()
    
    def destory(self):
        self.pipe.destory()
        MemoryCache.destory()

test = FuzzerTest()
test.start(10000,TestDataGenerate())