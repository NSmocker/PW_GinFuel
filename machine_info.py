#!/usr/bin/env python3
"""Machine fingerprint and RC4-encrypted machine-info report.

Mirrors the native client's LogicCheck::ReceiveMessage payload and the
Response fingerprint. Both results are cached because the component probes
(pwsh, DeviceIoControl) are slow and the server expects a login within
seconds of the Challenge.
"""

from __future__ import annotations

import ctypes
import os
import platform
import socket
import struct
import subprocess
import sys

_FINGERPRINT_CACHE: bytes | None = None
_MACHINE_INFO_CACHE: bytes | None = None


def _run_powershell(command: str):
    """Run a PowerShell probe when either PowerShell executable is present."""
    for executable in ("pwsh", "powershell"):
        try:
            return subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-Command",
                 command],
                capture_output=True, text=True, check=False)
        except FileNotFoundError:
            continue
    return None


def _windows_value(function_name: str, buffer_size: int) -> str:
    buffer = ctypes.create_unicode_buffer(buffer_size)
    size = ctypes.c_uint32(buffer_size)
    library = (ctypes.windll.advapi32 if function_name == "GetUserNameW"
               else ctypes.windll.kernel32)
    function = getattr(library, function_name)
    if not function(buffer, ctypes.byref(size)):
        return "-1"
    return buffer.value


def _disk_serial() -> str:
    if sys.platform != "win32":
        return "-1"
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileA.restype = ctypes.c_void_p
    handle = kernel32.CreateFileA(
        b"\\\\.\\PhysicalDrive0", 0, 0x1 | 0x2, None, 3, 0, None)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle and handle != invalid_handle:
        try:
            # sizeof(STORAGE_PROPERTY_QUERY) is 12 bytes; a 9-byte input makes
            # DeviceIoControl fail with ERROR_BAD_LENGTH (24).
            query = struct.pack("<II", 0, 0) + b"\0\0\0\0"
            buffer = ctypes.create_string_buffer(10240)
            returned = ctypes.c_uint32()
            if kernel32.DeviceIoControl(
                    handle, 0x2D1400, query, len(query), buffer,
                    len(buffer), ctypes.byref(returned), None):
                serial_offset = struct.unpack_from("<I", buffer.raw, 24)[0]
                if 0 < serial_offset < returned.value:
                    serial = buffer.raw[serial_offset:returned.value].split(
                        b"\0", 1)[0].decode("mbcs", errors="replace")
                    return serial.replace("\t", "").replace("\n", "").replace(
                        "\v", "").replace("\f", "").replace("\r", "").replace(
                            " ", "")
        finally:
            kernel32.CloseHandle(handle)
    result = _run_powershell(
        "(Get-CimInstance Win32_PhysicalMedia | "
        "Select-Object -First 1 -ExpandProperty SerialNumber)")
    if result is None:
        return "-2"
    return (result.stdout.strip() or "-2").replace("\t", "").replace("\r", "")


def _reg_read_string(root, path, name):
    """Mirror LogicCheck.cpp ReadRegString (string types only, 64-bit view)."""
    import winreg
    try:
        key = winreg.OpenKey(root, path, 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return ""
    try:
        value, vtype = winreg.QueryValueEx(key, name)
        if vtype in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            return value or ""
        return ""
    except OSError:
        return ""
    finally:
        winreg.CloseKey(key)


def _reg_read_dword(root, path, name):
    import winreg
    try:
        key = winreg.OpenKey(root, path, 0,
                             winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return 0
    try:
        value, vtype = winreg.QueryValueEx(key, name)
        if vtype == winreg.REG_DWORD:
            return int(value)
        return 0
    except OSError:
        return 0
    finally:
        winreg.CloseKey(key)


def _smbios_uuid() -> str:
    """Mirror GetSystemUuid: SMBIOS type-1 UUID via GetSystemFirmwareTable."""
    kernel32 = ctypes.windll.kernel32
    rsmb = 0x52534D42  # 'RSMB'
    kernel32.GetSystemFirmwareTable.restype = ctypes.c_uint32
    needed = kernel32.GetSystemFirmwareTable(rsmb, 0, None, 0)
    if needed == 0:
        return ""
    buffer = ctypes.create_string_buffer(needed)
    got = kernel32.GetSystemFirmwareTable(rsmb, 0, buffer, needed)
    if got == 0:
        return ""
    data = buffer.raw[:got]
    offset = 0
    while offset + 4 < len(data):
        stype = data[offset]
        length = data[offset + 1]
        if length == 0 or offset + length > len(data):
            break
        if stype == 1 and length >= 0x19:
            raw = data[offset + 4:offset + 20]
            return "%08x-%04x-%04x-%04x-%s" % (
                int.from_bytes(raw[0:4], "little"),
                int.from_bytes(raw[4:6], "little"),
                int.from_bytes(raw[6:8], "little"),
                int.from_bytes(raw[8:10], "big"),
                "".join("%02x" % b for b in raw[10:16]))
        nxt = offset + length
        while nxt + 1 < len(data):
            if data[nxt] == 0 and data[nxt + 1] == 0:
                nxt += 2
                break
            nxt += 1
        offset = nxt
    return ""


def _gpu_info() -> tuple[str, str]:
    """Mirror GetGpuName/GetGpuBios: (name, bios-or-driver-version)."""
    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32),
                    ("DeviceName", ctypes.c_wchar * 32),
                    ("DeviceString", ctypes.c_wchar * 128),
                    ("StateFlags", ctypes.c_uint32),
                    ("DeviceID", ctypes.c_wchar * 128),
                    ("DeviceKey", ctypes.c_wchar * 128)]

    user32 = ctypes.windll.user32
    primary_flag = 0x00000001
    index = 0
    device = DISPLAY_DEVICEW()
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(device)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            return "", ""
        if (device.StateFlags & primary_flag) or index == 0:
            break
        index += 1
    device_key = device.DeviceKey or ""
    prefix = "\\Registry\\Machine\\"
    if device_key.startswith(prefix):
        device_key = device_key[len(prefix):]
    import winreg
    bios = _reg_read_string(winreg.HKEY_LOCAL_MACHINE, device_key,
                            "HardwareInformation.BiosString")
    if not bios:
        bios = _reg_read_string(winreg.HKEY_LOCAL_MACHINE, device_key,
                                "DriverVersion")
    return device.DeviceString or "", bios


def _adapters_info() -> tuple[str, str]:
    """Mirror GetMacAndIps: (mac of first valid adapter, ip list)."""
    class SOCKADDR(ctypes.Structure):
        _fields_ = [("sa_family", ctypes.c_uint16),
                    ("sa_data", ctypes.c_uint8 * 14)]

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [("lpSockaddr", ctypes.POINTER(SOCKADDR)),
                    ("iSockaddrLength", ctypes.c_int)]

    class UNICAST_ADDRESS(ctypes.Structure):
        _fields_ = [("Length", ctypes.c_uint32), ("Flags", ctypes.c_uint32),
                    ("Next", ctypes.c_void_p), ("Address", SOCKET_ADDRESS)]

    class ADAPTER_ADDRESSES(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_uint32), ("IfIndex", ctypes.c_uint32),
            ("Next", ctypes.c_void_p), ("AdapterName", ctypes.c_void_p),
            ("FirstUnicastAddress", ctypes.POINTER(UNICAST_ADDRESS)),
            ("FirstAnycastAddress", ctypes.c_void_p),
            ("FirstMulticastAddress", ctypes.c_void_p),
            ("FirstDnsServerAddress", ctypes.c_void_p),
            ("DnsSuffix", ctypes.c_void_p), ("Description", ctypes.c_void_p),
            ("FriendlyName", ctypes.c_void_p),
            ("PhysicalAddress", ctypes.c_uint8 * 8),
            ("PhysicalAddressLength", ctypes.c_uint32),
            ("Flags", ctypes.c_uint32), ("Mtu", ctypes.c_uint32),
            ("IfType", ctypes.c_uint32), ("OperStatus", ctypes.c_uint32)]

    iphlpapi = ctypes.windll.iphlpapi
    flags = 0x0002 | 0x0004 | 0x0008  # skip anycast/multicast/dns
    size = ctypes.c_uint32(0)
    iphlpapi.GetAdaptersAddresses(0, flags, None, None, ctypes.byref(size))
    if size.value == 0:
        return "", ""
    buffer = ctypes.create_string_buffer(size.value)
    if iphlpapi.GetAdaptersAddresses(0, flags, None, buffer,
                                     ctypes.byref(size)) != 0:
        return "", ""

    IF_TYPE_LOOPBACK = 24
    IF_OPER_UP = 1
    mac = ""
    ips: list[str] = []
    adapter_ptr = ctypes.cast(buffer, ctypes.POINTER(ADAPTER_ADDRESSES))
    adapter = adapter_ptr.contents
    while adapter:
        valid = (adapter.PhysicalAddressLength >= 6
                 and adapter.IfType != IF_TYPE_LOOPBACK
                 and adapter.OperStatus == IF_OPER_UP)
        if valid:
            if not mac:
                mac = "-".join("%02x" % b for b in
                               adapter.PhysicalAddress[:adapter.PhysicalAddressLength])
            ua_ptr = adapter.FirstUnicastAddress
            while ua_ptr:
                ua = ua_ptr.contents
                sa = ua.Address.lpSockaddr.contents
                addr_bytes = bytes(sa.sa_data)
                family = sa.sa_family
                text = ""
                try:
                    if family == 2 and len(addr_bytes) >= 6:
                        text = socket.inet_ntop(socket.AF_INET,
                                                addr_bytes[4:8])
                    elif family == 23 and len(addr_bytes) >= 26:
                        text = socket.inet_ntop(socket.AF_INET6,
                                                addr_bytes[8:24])
                        scope = int.from_bytes(addr_bytes[24:28], "little")
                        if scope and text.startswith("fe80"):
                            text = f"{text}%{scope}"
                except (OSError, ValueError):
                    text = ""
                if text and text not in ("127.0.0.1", "::1"):
                    ips.append(text)
                ua_ptr = (ctypes.cast(ua.Next,
                                      ctypes.POINTER(UNICAST_ADDRESS))
                          if ua.Next else None)
        adapter = (ctypes.cast(adapter.Next,
                               ctypes.POINTER(ADAPTER_ADDRESSES)).contents
                   if adapter.Next else None)
    return mac, ",".join(ips)


def _disk_descriptor() -> tuple[str, str]:
    """Mirror GetDiskSerialAndModel: (serial, model) C-strings."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW("\\\\.\\PhysicalDrive0", 0, 0x1 | 0x2,
                                  None, 3, 0, None)
    invalid = ctypes.c_void_p(-1).value
    if not handle or handle == invalid:
        return "", ""
    try:
        query = struct.pack("<II", 0, 0) + b"\0\0\0\0"
        buffer = ctypes.create_string_buffer(1024)
        returned = ctypes.c_uint32()
        if not kernel32.DeviceIoControl(
                handle, 0x2D1400, query, len(query), buffer, len(buffer),
                ctypes.byref(returned), None):
            return "", ""
        blob = buffer.raw[:returned.value]
        if len(blob) < 36:
            return "", ""
        def cstring(offset):
            if offset <= 0 or offset >= len(blob):
                return ""
            end = blob.find(b"\0", offset)
            return blob[offset:end if end >= 0 else len(blob)].decode(
                "latin-1")
        serial = cstring(struct.unpack_from("<I", blob, 24)[0])
        model = cstring(struct.unpack_from("<I", blob, 16)[0])
        if not model:
            model = cstring(struct.unpack_from("<I", blob, 20)[0])
        if not model:
            model = cstring(struct.unpack_from("<I", blob, 12)[0])
        return serial, model
    finally:
        kernel32.CloseHandle(handle)


def _exe_creation_time() -> int:
    paths = [r"D:\CyberPW Gameplay\element\elementclient.exe", sys.executable]
    for path in paths:
        try:
            return int(os.stat(path).st_ctime)
        except OSError:
            continue
    return 0


def build_machine_info() -> bytes:
    """Replicate LogicCheck::ReceiveMessage (RC4-encrypted system report)."""
    global _MACHINE_INFO_CACHE
    if _MACHINE_INFO_CACHE is not None:
        return _MACHINE_INFO_CACHE

    import winreg
    hklm = winreg.HKEY_LOCAL_MACHINE
    is64 = "x64" if platform.machine().endswith("64") else "x86"
    product_id = _reg_read_string(
        hklm, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductId")
    machine_guid = _reg_read_string(hklm, r"SOFTWARE\Microsoft\Cryptography",
                                    "MachineGuid")
    client_id = _reg_read_string(hklm, r"SOFTWARE\Microsoft\SQMClient",
                                 "MachineId") or machine_guid
    identifier = _smbios_uuid()
    if not identifier:
        identifier = platform.node()
    install_date = _reg_read_dword(
        hklm, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "InstallDate")
    winver = sys.getwindowsversion()
    system_version = f"{winver.major}.{winver.minor}.{winver.build}"
    cpu_name = _reg_read_string(
        hklm, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        "ProcessorNameString")
    gpu_name, gpu_bios = _gpu_info()
    ram_mb = 0
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32),
                    ("memory_load", ctypes.c_uint32),
                    ("total_phys", ctypes.c_uint64),
                    ("avail_phys", ctypes.c_uint64),
                    ("total_page_file", ctypes.c_uint64),
                    ("avail_page_file", ctypes.c_uint64),
                    ("total_virtual", ctypes.c_uint64),
                    ("avail_virtual", ctypes.c_uint64),
                    ("avail_extended_virtual", ctypes.c_uint64)]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
    if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        ram_mb = status.total_phys // (1024 * 1024)
    disk_serial, disk_model = _disk_descriptor()
    mac, ip_list = _adapters_info()

    payload = "|".join([
        is64, product_id, "1", machine_guid, "2", client_id, "3",
        identifier, "4", str(install_date) if install_date else "", "5",
        system_version, "6", cpu_name, "7", gpu_name, "8", gpu_bios, "9",
        str(ram_mb), "a", disk_serial, "b", disk_model, "c", mac, "d",
        ip_list, "e", str(_exe_creation_time()),
    ])
    data = bytearray(payload.encode("utf-8"))
    key = b"\x34\x56\x87\x48"
    perm = list(range(256))
    j = 0
    for i in range(256):
        j = (j + perm[i] + key[i % 4]) & 0xFF
        perm[i], perm[j] = perm[j], perm[i]
    i = 0
    j = 0
    for index in range(len(data)):
        i = (i + 1) & 0xFF
        j = (j + perm[i]) & 0xFF
        perm[i], perm[j] = perm[j], perm[i]
        data[index] ^= perm[(perm[i] + perm[j]) & 0xFF]
    _MACHINE_INFO_CACHE = bytes(data)
    return _MACHINE_INFO_CACHE


def build_fingerprint() -> bytes:
    """Build the same UTF-8 machine-info shape as the native client.

    The result is cached: the server expects the Response within seconds of
    the Challenge, and the component probes (pwsh, DeviceIoControl) are slow,
    so callers should trigger the build before connecting.
    """
    global _FINGERPRINT_CACHE
    if _FINGERPRINT_CACHE is not None:
        return _FINGERPRINT_CACHE
    cpu = _native_cpu_id()
    ram_mb = 0
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32),
                        ("memory_load", ctypes.c_uint32),
                        ("total_phys", ctypes.c_uint64),
                        ("avail_phys", ctypes.c_uint64),
                        ("total_page_file", ctypes.c_uint64),
                        ("avail_page_file", ctypes.c_uint64),
                        ("total_virtual", ctypes.c_uint64),
                        ("avail_virtual", ctypes.c_uint64),
                        ("avail_extended_virtual", ctypes.c_uint64)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalMemoryStatusEx.argtypes = [
            ctypes.POINTER(MemoryStatus)]
        kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram_mb = status.total_phys // (1024 * 1024)
    result = f"MK|{cpu}|{ram_mb}|{_disk_serial()}|".encode(
        "utf-8") + _windows_value("GetComputerNameW", 256).encode(
            "utf-8") + b"|" + _windows_value("GetUserNameW", 256).encode("utf-8") + b"\0"
    _FINGERPRINT_CACHE = result
    return result


def _native_cpu_id() -> str:
    if sys.platform == "win32":
        command = (
            "Add-Type -TypeDefinition 'using System; using "
            "System.Runtime.Intrinsics.X86; public static class "
            "FingerprintCpu { public static void Main(){ var r0 = "
            "X86Base.CpuId(0,0); var r1 = X86Base.CpuId(1,0); "
            "Console.WriteLine(r0.Ecx.ToString() + Convert.ToChar(124) + "
            "r1.Eax.ToString()); }}'; "
            "[FingerprintCpu]::Main()"
        )
        result = _run_powershell(command)
        if result is None:
            return platform.processor() or platform.machine() or "Unk"
        fields = result.stdout.strip().split("|")
        if len(fields) == 2:
            vendor = {"1818588270": "Intel", "1145913699": "AMD"}.get(
                fields[0], "Unk")
            try:
                return f"{vendor} {int(fields[1])}"
            except ValueError:
                pass
    return platform.processor() or platform.machine() or "Unk"
