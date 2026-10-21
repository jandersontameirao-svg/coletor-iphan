"""Limites do parser no Windows via Job Object; POSIX é limitado no filho."""
import os

def attach(proc,memory,cpu):
    if os.name!='nt': return lambda:None
    import ctypes as ct
    from ctypes import wintypes as wt
    class Basic(ct.Structure):
        _fields_=[('PerProcessUserTimeLimit',ct.c_longlong),('PerJobUserTimeLimit',ct.c_longlong),('LimitFlags',wt.DWORD),('MinimumWorkingSetSize',ct.c_size_t),('MaximumWorkingSetSize',ct.c_size_t),('ActiveProcessLimit',wt.DWORD),('Affinity',ct.c_size_t),('PriorityClass',wt.DWORD),('SchedulingClass',wt.DWORD)]
    class IO(ct.Structure):
        _fields_=[(x,ct.c_ulonglong) for x in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
    class Extended(ct.Structure):
        _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ct.c_size_t),('JobMemoryLimit',ct.c_size_t),('PeakProcessMemoryUsed',ct.c_size_t),('PeakJobMemoryUsed',ct.c_size_t)]
    kernel=ct.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ct.c_void_p,wt.LPCWSTR];kernel.CreateJobObjectW.restype=wt.HANDLE
    kernel.SetInformationJobObject.argtypes=[wt.HANDLE,ct.c_int,ct.c_void_p,wt.DWORD];kernel.SetInformationJobObject.restype=wt.BOOL
    kernel.AssignProcessToJobObject.argtypes=[wt.HANDLE,wt.HANDLE];kernel.AssignProcessToJobObject.restype=wt.BOOL
    kernel.CloseHandle.argtypes=[wt.HANDLE];kernel.CloseHandle.restype=wt.BOOL
    handle=kernel.CreateJobObjectW(None,None)
    if not handle: raise OSError(ct.get_last_error(),'Job Object indisponível')
    limits=Extended();limits.BasicLimitInformation.LimitFlags=0x2|0x100|0x2000
    limits.BasicLimitInformation.PerProcessUserTimeLimit=cpu*10_000_000;limits.ProcessMemoryLimit=memory
    if not kernel.SetInformationJobObject(handle,9,ct.byref(limits),ct.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle,wt.HANDLE(int(proc._handle))):
        error=ct.get_last_error();kernel.CloseHandle(handle);proc.kill();proc.wait();raise OSError(error,'Não foi possível limitar o parser')
    return lambda:kernel.CloseHandle(handle)
