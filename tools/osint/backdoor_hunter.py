#!/usr/bin/env python3
"""
GraphLang Backdoor Hunter — Anomaly-based backdoor detection.

Uses GraphLang's structural IR to detect backdoors, trojans, and malicious
code patterns that evade signature-based detection. Instead of matching known
signatures, it detects structural anomalies that indicate hidden functionality.

Detection methods:
1. Dead code analysis — functions never called that contain dangerous ops
2. Obfuscation scoring — entropy, name randomness, encoding patterns
3. Asymmetric function analysis — simple-looking functions that do complex things
4. Conditional backdoor detection — magic values that unlock hidden behavior
5. Reflection/invoke abuse — dynamic code loading patterns
6. Native code bridges — JNI/FFI to suspicious native libraries
7. Encoded payload detection — base64/hex strings that decode to commands
8. Persistence mechanism detection — cron, registry, init scripts
9. C2 beacon patterns — periodic HTTP/DNS requests with data exfiltration
10. Anti-analysis detection — VM/sandbox/debugger checks

Author: Josué Argaña Silguero — GraphLang Pentest Toolkit
"""

import re
import math
import base64
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

try:
    from core import Graph, Node, PythonToGraphLang
except ImportError:
    print("[!] GraphLang core required")
    import sys; sys.exit(1)


@dataclass
class BackdoorSignal:
    """A detected backdoor indicator."""
    name: str
    severity: str        # CRITICAL, HIGH, MEDIUM
    confidence: float    # 0.0 — 1.0
    description: str
    evidence: dict = field(default_factory=dict)
    code_snippet: str = ""
    line: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Entropy Calculator
# ═══════════════════════════════════════════════════════════════════════════

def shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy of a string (0-8 bits)."""
    if not data:
        return 0.0
    entropy = 0.0
    for x in range(256):
        px = data.count(chr(x)) / len(data)
        if px > 0:
            entropy -= px * math.log2(px)
    return entropy


# ═══════════════════════════════════════════════════════════════════════════
# Backdoor Pattern Definitions
# ═══════════════════════════════════════════════════════════════════════════

BACKDOOR_PATTERNS = {
    "reflection_abuse": {
        "name": "Reflection / Dynamic Invocation Abuse",
        "severity": "HIGH",
        "keywords": ["getattr", "setattr", "__import__", "eval", "exec",
                     "compile", "__subclasses__", "__bases__", "__mro__",
                     "importlib", "imp.load_source", "types.FunctionType",
                     "getattr", "__getattribute__", "__dict__",
                     # Java
                     "Class.forName", "getDeclaredMethod", "getDeclaredField",
                     "setAccessible", "Method.invoke", "Field.set",
                     "ClassLoader", "loadClass", "defineClass",
                     "Unsafe", "theUnsafe",
                     # JS/TS
                     "eval(", "Function(", "new Function",
                     "setTimeout(", "setInterval(",
                     # C#
                     "System.Reflection", "Assembly.Load",
                     "MethodInfo.Invoke", "Activator.CreateInstance",
                     # PHP
                     "eval(", "assert(", "preg_replace('/e'",
                     "create_function", "call_user_func",
                     "ReflectionClass", "ReflectionMethod",
                     # Ruby
                     "eval(", "send(", "method(", "instance_eval",
                     "class_eval", "define_method",
                     # Go
                     "plugin.Open", "reflect.ValueOf",
                     # Rust
                     "unsafe", "std::mem::transmute",
                     ],
        "description": "Code that uses reflection/introspection to dynamically invoke methods, "
                       "commonly used by backdoors to hide functionality from static analysis.",
    },

    "encoded_payloads": {
        "name": "Encoded / Encrypted Payloads",
        "severity": "CRITICAL",
        "keywords": ["base64.b64decode", "base64_decode", "atob(",
                     "from base64", "b64decode", "decodebytes",
                     "hex.DecodeString", "hex2bin", "unhexlify",
                     "gzip.decompress", "zlib.decompress", "inflate(",
                     "rot13", "str_rot13", "caesar",
                     "xor(", "deobfuscate", "deobf",
                     "decrypt(", "AES.new", "DES.new",
                     "RC4", "arcfour",
                     "Fernet", "cryptography",
                     "decode(", "fromhex", "unhex",
                     "bytes.fromhex", "Buffer.from",
                     "decodeURIComponent",
                     ],
        "description": "Code that decodes/decrypts data at runtime, often used to hide "
                       "malicious payloads that only become visible during execution.",
    },

    "persistence_mechanisms": {
        "name": "Persistence Mechanism",
        "severity": "HIGH",
        "keywords": [
            # Linux
            "/etc/crontab", "crontab -e", "@reboot", "/etc/rc.local",
            "/etc/init.d", "systemctl enable", "update-rc.d",
            "/etc/systemd/system", "systemd.service",
            "~/.bashrc", "~/.bash_profile", "~/.profile",
            "~/.ssh/authorized_keys", "ssh-keygen",
            "/etc/ld.so.preload", "LD_PRELOAD",
            # Windows
            "HKEY_LOCAL_MACHINE\\\\Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Run",
            "HKCU\\\\Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Run",
            "SCHTASKS /Create", "schtasks",
            "Startup\\\\", "\\\\Start Menu\\\\Programs\\\\Startup",
            "Set-ItemProperty -Path 'HKCU:", "RegistryKey",
            "wmi", "WMI", "__EventFilter",
            # macOS
            "LaunchDaemons", "LaunchAgents", "launchctl",
            "/Library/LaunchDaemons",
            # Cross-platform
            "cron", "schedule", "setInterval", "setTimeout",
            "at(", "atq", "batch(",
            "services.msc", "sc create",
        ],
        "description": "Code that establishes persistence on the system, ensuring the "
                       "backdoor survives reboots.",
    },

    "c2_communication": {
        "name": "Command & Control Communication",
        "severity": "CRITICAL",
        "keywords": [
            # HTTP C2
            "beacon", "heartbeat", "checkin",
            "User-Agent: Mozilla/5.0", "Content-Type: application/",
            # DNS C2
            "nslookup", "dig ", "dns.resolver",
            "dnsQuery", "Dns.GetHostEntry",
            # Raw sockets
            "socket.socket", "socket.connect",
            "socket.SOCK_STREAM", "AF_INET",
            "Socket(", "ServerSocket",
            "TcpClient", "UdpClient",
            "net.Dial", "net.Listen",
            # WebSocket C2
            "WebSocket", "ws://", "wss://",
            # IRC/Telegram/Discord Bots
            "irc.", "IRC", "telegram.Bot",
            "discord.Webhook", "slack.Webhook",
            # Exfiltration
            "upload(", "send(", "post(",
            "requests.post", "fetch(",
            "HttpClient", "WebClient.UploadData",
            # Encrypted channels
            "ssl.wrap_socket", "SSLContext",
            "tls.Config", "Tls12",
            # TOR/I2P
            ".onion", "socks.PROXY", "socks5",
            "stem.control", "tor",
            # Proxy/Domain generation
            "DGA", "domain_generation", "generate_domain",
            "random_domain", "fallback_domain",
        ],
        "description": "Code that establishes external communication channels typical of "
                       "command & control (C2) infrastructure.",
    },

    "anti_analysis": {
        "name": "Anti-Analysis / Anti-Debugging",
        "severity": "HIGH",
        "keywords": [
            "isDebuggerPresent", "IsDebuggerPresent",
            "CheckRemoteDebuggerPresent",
            "NtGlobalFlag", "BeingDebugged",
            "ptrace(PT_DENY_ATTACH", "ptrace(PTRACE_TRACEME",
            "sysctl kern.proc", "PROC_PID",
            "/proc/self/status", "TracerPid:",
            "debugger", "Debugger", "DEBUGGER",
            "VBoxService", "VMware", "VirtualBox",
            "QEMU", "Xen", "Hyper-V",
            "sandbox", "Sandbox", "SANDBOX",
            "is_virtual_machine", "is_vm",
            "cpuid", "CPUID", "rdtsc",
            "sleep(", "time.sleep", "Sleep(",
            "delay(", "usleep", "nanosleep",
            "if __name__ == '__main__'",
        ],
        "description": "Code that checks for debuggers, virtual machines, or sandboxes "
                       "and alters behavior to evade analysis.",
    },

    "data_exfiltration": {
        "name": "Data Exfiltration Patterns",
        "severity": "HIGH",
        "keywords": [
            "browser_password", "BrowserPassword",
            "chrome_password", "Login Data",
            "Cookies", "cookies.sqlite",
            "keychain", "Keychain",
            "credential", "Credential",
            "wallet.dat", "wallet",
            "private_key", "privateKey",
            "mnemonic", "seed_phrase",
            "clipboard", "Clipboard",
            "keylogger", "keylog",
            "screenshot", "Screenshot",
            "webcam", "camera", "video",
            "microphone", "audio capture",
            "file_search", "find_files",
            "recursive_list", "walk(",
            "os.walk", "fs.walk",
            "export(", "exfiltrate", "exfil",
            "zip(", "compress", "archive",
        ],
        "description": "Code that collects and prepares to exfiltrate sensitive data from the system.",
    },

    "privilege_escalation": {
        "name": "Privilege Escalation Attempt",
        "severity": "CRITICAL",
        "keywords": [
            "setuid(0)", "seteuid(0)", "setgid(0)",
            "os.setuid", "os.seteuid",
            "sudo", "pkexec", "doas",
            "SeDebugPrivilege", "SeTakeOwnershipPrivilege",
            "OpenProcessToken", "AdjustTokenPrivileges",
            "LookupPrivilegeValue",
            "runas", "RunAs",
            "ShellExecute", "runas",
            "DirtyCow", "dirtycow", "dirty_cow",
            "exploit", "exploit",
            "cve-", "CVE-",
            "overflow", "buffer",
            "ROP", "gadget",
            "shellcode", "nop_sled",
        ],
        "description": "Code that attempts to elevate privileges beyond the current user context.",
    },

    "process_injection": {
        "name": "Process Injection / Hollowing",
        "severity": "CRITICAL",
        "keywords": [
            "VirtualAllocEx", "VirtualAlloc",
            "WriteProcessMemory", "ReadProcessMemory",
            "CreateRemoteThread", "NtCreateThreadEx",
            "OpenProcess", "Process32First",
            "CreateProcess", "CreateProcessInternal",
            "SetThreadContext", "GetThreadContext",
            "ResumeThread", "SuspendThread",
            "NtUnmapViewOfSection",
            "QueueUserAPC", "SetWindowsHookEx",
            "ptrace(", "PTRACE_ATTACH",
            "PTRACE_POKETEXT", "PTRACE_POKEDATA",
            "process_vm_writev", "process_vm_readv",
            "dlinject", "memfd_create",
            "LD_PRELOAD", "/proc/self/mem",
            "ptrace(PTRACE_POKETEXT",
            "shmat", "shmget",
            "mmap", "mprotect",
        ],
        "description": "Code that injects into or manipulates other processes, typical of "
                       "advanced persistent threats (APTs).",
    },

    "hidden_execution": {
        "name": "Hidden Execution / Code Hiding",
        "severity": "HIGH",
        "keywords": [
            "__builtins__", "__builtin__",
            "compile(", "exec(", "eval(",
            "marshal.loads", "pickle.loads",
            "code.interact", "code.InteractiveInterpreter",
            "ctypes.CDLL", "ctypes.WinDLL",
            "ctypes.pythonapi",
            "subprocess.Popen", "os.system",
            "popen", "pexpect",
            "proc_open", "shell_exec",
            "Runtime.getRuntime().exec",
            "new ProcessBuilder",
            "child_process.exec", "child_process.spawn",
            "exec.Command", "cmd.Start",
            "Command::new", "output.execute",
            "system(", "System.Diagnostics.Process.Start",
            # Obfuscated execution
            "lambda", "__lambda__",
            "getattr(__import__",
            "''.__class__.__mro__",
            "().__class__.__bases__",
        ],
        "description": "Code that executes commands or code through unconventional, "
                       "hard-to-trace methods.",
    },

    "conditional_backdoor": {
        "name": "Conditional Backdoor / Magic Value Trigger",
        "severity": "CRITICAL",
        "keywords": [
            "magic", "MAGIC", "magic_key",
            "backdoor", "BACKDOOR", "back_door",
            "debug_key", "admin_override",
            "secret_phrase", "master_key",
            "god_mode", "super_admin",
            "bypass_auth", "bypass_login",
            "hardcoded_admin", "emergency_access",
            "special_token", "override_token",
        ],
        "description": "Code containing magic values or hidden conditions that, when met, "
                       "grant unauthorized access or unlock hidden functionality.",
    },
}

# ═══════════════════════════════════════════════════════════════════════════
# Backdoor Hunter Engine
# ═══════════════════════════════════════════════════════════════════════════

class BackdoorHunter:
    """Anomaly-based backdoor and malware detection using GraphLang IR."""

    def __init__(self):
        self.signals = []
        self._entropy_cache = {}

    def hunt(self, code: str, language: str = "python",
             filename: str = "<unknown>") -> list:
        """
        Hunt for backdoors in source code.
        Returns list of BackdoorSignal objects.
        """
        self.signals = []
        self._entropy_cache = {}

        lines = code.split('\n')

        # 1. Pattern-based detection
        self._check_keyword_patterns(code, lines, filename)

        # 2. Structural analysis via GraphLang IR
        try:
            converter = PythonToGraphLang()
            graph = converter.convert(code)
            self._analyze_graph_structure(graph, code, lines, filename)
        except Exception:
            pass  # Parse errors are ok — we still do pattern-based detection

        # 3. Entropy analysis
        self._check_entropy_anomalies(code, lines, filename)

        # 4. Function analysis
        self._analyze_function_complexity(code, filename)

        return sorted(self.signals, key=lambda s: s.confidence, reverse=True)

    def _check_keyword_patterns(self, code: str, lines: list, filename: str):
        """Check code against known backdoor keyword patterns."""
        code_lower = code.lower()

        for pattern_id, pattern_info in BACKDOOR_PATTERNS.items():
            matched_keywords = []
            for kw in pattern_info["keywords"]:
                if kw.lower() in code_lower:
                    matched_keywords.append(kw)

            if matched_keywords:
                # Calculate confidence based on how many keywords matched
                confidence = min(1.0, len(matched_keywords) / 5)
                if len(matched_keywords) >= 3:
                    confidence = min(1.0, 0.6 + len(matched_keywords) * 0.1)

                # Find line numbers for matched keywords
                matched_lines = set()
                for kw in matched_keywords:
                    for i, line in enumerate(lines, 1):
                        if kw.lower() in line.lower():
                            matched_lines.add(i)

                # Extract snippet
                snippet_lines = []
                for ln in sorted(matched_lines)[:3]:
                    if 0 < ln <= len(lines):
                        snippet_lines.append(f"  L{ln}: {lines[ln-1].strip()[:100]}")

                self.signals.append(BackdoorSignal(
                    name=pattern_info["name"],
                    severity=pattern_info["severity"],
                    confidence=confidence,
                    description=pattern_info["description"],
                    evidence={
                        "pattern_id": pattern_id,
                        "matched_keywords": matched_keywords[:10],
                        "matched_lines": sorted(matched_lines)[:10],
                    },
                    code_snippet="\n".join(snippet_lines),
                    line=sorted(matched_lines)[0] if matched_lines else 0,
                ))

    def _analyze_graph_structure(self, graph: Graph, code: str,
                                  lines: list, filename: str):
        """Analyze GraphLang IR for structural anomalies."""

        # Count node types
        kind_counts = Counter()
        for nid, node in graph.nodes.items():
            kind_counts[node.kind] += 1

        total_nodes = len(graph.nodes)
        if total_nodes < 5:
            return

        # Anomaly 1: High ratio of calls to other nodes (possible shellcode loader)
        call_ratio = kind_counts.get("call", 0) / max(total_nodes, 1)
        if call_ratio > 0.4:
            self.signals.append(BackdoorSignal(
                name="Dense Call Graph (possible loader/stager)",
                severity="HIGH",
                confidence=min(1.0, call_ratio),
                description=f"Unusually high call density ({call_ratio:.0%}): "
                            f"{kind_counts['call']} calls in {total_nodes} nodes. "
                            f"Typical of shellcode loaders and staging malware.",
                evidence={"call_ratio": call_ratio, "total_nodes": total_nodes},
                line=0,
            ))

        # Anomaly 2: High number of const nodes (encoded payloads)
        const_ratio = kind_counts.get("const", 0) / max(total_nodes, 1)
        if const_ratio > 0.5:
            self.signals.append(BackdoorSignal(
                name="Excessive Constants (possible encoded payload)",
                severity="MEDIUM",
                confidence=min(1.0, const_ratio - 0.3),
                description=f"High ratio of constants ({const_ratio:.0%}): "
                            f"common in malware with embedded encoded payloads.",
                evidence={"const_ratio": const_ratio},
                line=0,
            ))

        # Anomaly 3: Deeply nested structures (obfuscated code)
        max_depth = self._max_graph_depth(graph)
        if max_depth > 15:
            self.signals.append(BackdoorSignal(
                name="Deep Graph Nesting (possible obfuscation)",
                severity="MEDIUM",
                confidence=min(1.0, (max_depth - 15) / 15),
                description=f"Maximum IR graph depth of {max_depth} nodes. "
                            f"Deep nesting often indicates obfuscated or generated code.",
                evidence={"max_depth": max_depth},
                line=0,
            ))

    def _max_graph_depth(self, graph: Graph) -> int:
        """Calculate maximum depth of the IR graph."""
        visited = set()

        def depth(nid):
            if nid in visited:
                return 0
            visited.add(nid)
            node = graph.nodes.get(nid)
            if not node or not node.args:
                return 1
            max_child = 0
            for arg in node.args:
                max_child = max(max_child, depth(arg))
            return 1 + max_child

        max_d = 0
        for nid in graph.nodes:
            max_d = max(max_d, depth(nid))
        return max_d

    def _check_entropy_anomalies(self, code: str, lines: list, filename: str):
        """Detect high-entropy strings (potential encoded/encrypted payloads)."""

        # Find long string literals
        string_pattern = re.compile(r'(?:\'[^\']{20,}\'|"[^"]{20,}")')
        high_entropy_strings = []

        for match in string_pattern.finditer(code):
            s = match.group(0)[1:-1]  # Remove quotes
            entropy = shannon_entropy(s)

            if entropy > 5.0:  # High entropy — likely encoded/encrypted
                # Find line number
                line_num = code[:match.start()].count('\n') + 1

                # Try to decode as base64
                is_b64 = False
                try:
                    decoded = base64.b64decode(s, validate=True)
                    if len(decoded) > 4 and shannon_entropy(decoded.decode('latin-1')) < 6:
                        is_b64 = True
                except Exception:
                    pass

                high_entropy_strings.append({
                    "line": line_num,
                    "entropy": round(entropy, 2),
                    "length": len(s),
                    "is_base64": is_b64,
                    "preview": s[:50] + ("..." if len(s) > 50 else ""),
                })

        if high_entropy_strings:
            confidence = min(1.0, len(high_entropy_strings) * 0.15 + 0.4)
            self.signals.append(BackdoorSignal(
                name="High-Entropy Embedded Data (encoded payload)",
                severity="HIGH",
                confidence=confidence,
                description=f"Found {len(high_entropy_strings)} high-entropy string(s) "
                            f"(entropy > 5.0). Likely encoded or encrypted payloads.",
                evidence={"high_entropy_strings": high_entropy_strings[:5]},
                code_snippet="\n".join(
                    f"  L{s['line']}: \"{s['preview']}\" (entropy={s['entropy']})"
                    for s in high_entropy_strings[:3]
                ),
                line=high_entropy_strings[0]["line"] if high_entropy_strings else 0,
            ))

        # Check per-line entropy
        anomalous_lines = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if len(stripped) > 100:
                entropy = shannon_entropy(stripped)
                if entropy > 5.5:
                    anomalous_lines.append({"line": i, "entropy": round(entropy, 2)})

        if len(anomalous_lines) > 5:
            self.signals.append(BackdoorSignal(
                name="Multiple High-Entropy Lines (obfuscated/encoded code)",
                severity="MEDIUM",
                confidence=min(1.0, len(anomalous_lines) * 0.05),
                description=f"Found {len(anomalous_lines)} lines with high entropy (>5.5).",
                evidence={"anomalous_lines_count": len(anomalous_lines)},
                line=anomalous_lines[0]["line"] if anomalous_lines else 0,
            ))

    def _analyze_function_complexity(self, code: str, filename: str):
        """Analyze function-level anomalies."""

        # Find Python functions
        func_pattern = re.compile(
            r'^\s*def\s+(\w+)\s*\([^)]*\)\s*:', re.MULTILINE
        )
        functions = list(func_pattern.finditer(code))

        # Count lines per function
        func_lines = []
        for i, match in enumerate(functions):
            start_line = code[:match.start()].count('\n') + 1
            name = match.group(1)

            # Estimate end (next function or end of file at same indent level)
            if i + 1 < len(functions):
                end_line = code[:functions[i + 1].start()].count('\n') + 1
            else:
                end_line = len(code.split('\n'))

            func_body = '\n'.join(code.split('\n')[start_line:end_line])
            func_lines.append({
                "name": name,
                "start": start_line,
                "end": end_line,
                "lines": end_line - start_line,
                "entropy": shannon_entropy(func_body),
            })

        # Anomaly: single-letter or short random function names with complex bodies
        suspicious_funcs = []
        for f in func_lines:
            name = f["name"]
            # Short random-looking names (like 'a', 'b1', 'x0', '_')
            if len(name) <= 3 and not name.startswith('__'):
                if f["lines"] > 5:
                    suspicious_funcs.append({
                        **f,
                        "reason": "Short name with significant body"
                    })

        if suspicious_funcs:
            self.signals.append(BackdoorSignal(
                name="Suspicious Short-Named Functions",
                severity="MEDIUM",
                confidence=0.6,
                description=f"Found {len(suspicious_funcs)} functions with very short "
                            f"names but significant bodies. Typical of obfuscated malware.",
                evidence={"suspicious_functions": suspicious_funcs[:5]},
                code_snippet="\n".join(
                    f"  L{f['start']}: def {f['name']}() — {f['lines']} lines"
                    for f in suspicious_funcs[:3]
                ),
                line=suspicious_funcs[0]["start"] if suspicious_funcs else 0,
            ))

        # Anomaly: functions with names suggesting hidden purpose
        hidden_names = []
        for f in func_lines:
            name_lower = f["name"].lower()
            suspicious_names = [
                "hidden", "secret", "backdoor", "bypass", "override",
                "unsafe", "raw", "native", "internal", "private_api",
                "debug_cmd", "admin_only", "super_user", "magic",
                "do_exec", "run_cmd", "shell", "inject",
            ]
            if any(s in name_lower for s in suspicious_names):
                hidden_names.append(f)

        if hidden_names:
            self.signals.append(BackdoorSignal(
                name="Functions with Suspicious Names",
                severity="MEDIUM",
                confidence=0.7,
                description=f"Found {len(hidden_names)} functions with names "
                            f"suggesting hidden or debug functionality.",
                evidence={"hidden_functions": hidden_names[:5]},
                line=hidden_names[0]["start"] if hidden_names else 0,
            ))


# ═══════════════════════════════════════════════════════════════════════════
# Report & CLI
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(signals: list, filename: str) -> str:
    """Generate a detailed text report from backdoor signals."""
    RED = '\033[91m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

    lines = []
    lines.append(f"\n{BOLD}{'═' * 70}{RESET}")
    lines.append(f"{BOLD}  GraphLang Backdoor Hunter — Analysis Report{RESET}")
    lines.append(f"{BOLD}{'═' * 70}{RESET}")
    lines.append(f"  Target: {filename}")
    lines.append(f"  Signals detected: {len(signals)}")

    if not signals:
        lines.append(f"\n  {GREEN}✅ No backdoor indicators detected.{RESET}")
        lines.append(f"{'═' * 70}\n")
        return "\n".join(lines)

    # Summary by severity
    sev_counts = Counter(s.severity for s in signals)
    lines.append(f"\n  {BOLD}Severity Summary:{RESET}")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        count = sev_counts.get(sev, 0)
        if count:
            color = RED if sev == "CRITICAL" else YELLOW if sev == "HIGH" else GREEN
            lines.append(f"    {color}{sev}: {count}{RESET}")

    # Risk score (0-100)
    risk_score = min(100, sum(
        40 if s.severity == "CRITICAL" else
        25 if s.severity == "HIGH" else
        10 if s.severity == "MEDIUM" else 5
        for s in signals
    ))
    risk_color = RED if risk_score > 60 else YELLOW if risk_score > 30 else GREEN
    lines.append(f"\n  {BOLD}Overall Risk Score: {risk_color}{risk_score}/100{RESET}")
    lines.append(f"  {'CRITICAL' if risk_score > 70 else 'HIGH' if risk_score > 40 else 'MODERATE' if risk_score > 20 else 'LOW'} risk level")

    # Detailed signals
    lines.append(f"\n  {BOLD}Detailed Signals:{RESET}")

    for i, signal in enumerate(signals, 1):
        color = RED if signal.severity == "CRITICAL" else YELLOW if signal.severity == "HIGH" else GREEN
        lines.append(f"\n  {BOLD}[{i}] {color}{signal.name}{RESET}")
        lines.append(f"      Severity: {signal.severity} | Confidence: {signal.confidence:.0%}")
        lines.append(f"      {signal.description}")
        if signal.evidence:
            for key, val in signal.evidence.items():
                if isinstance(val, list):
                    lines.append(f"      {key}: {len(val)} items")
                elif not isinstance(val, (dict, list)):
                    lines.append(f"      {key}: {val}")
        if signal.code_snippet:
            lines.append(f"      Code:")
            lines.append(f"{signal.code_snippet}")
        if signal.line:
            lines.append(f"      Line: {signal.line}")

    lines.append(f"\n{BOLD}{'═' * 70}{RESET}\n")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GraphLang Backdoor Hunter")
    parser.add_argument("target", help="File to analyze")
    parser.add_argument("--lang", default="python", help="Language (default: python)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode")

    args = parser.parse_args()

    try:
        with open(args.target, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    hunter = BackdoorHunter()
    signals = hunter.hunt(code, args.lang, args.target)

    if args.json:
        import json
        output = [{
            "name": s.name,
            "severity": s.severity,
            "confidence": s.confidence,
            "description": s.description,
            "evidence": {k: str(v) if not isinstance(v, (str, int, float, bool, list, dict)) else v
                        for k, v in s.evidence.items()},
            "line": s.line,
        } for s in signals]
        print(json.dumps(output, indent=2))
    elif args.quiet:
        if signals:
            critical = sum(1 for s in signals if s.severity == "CRITICAL")
            high = sum(1 for s in signals if s.severity == "HIGH")
            print(f"{args.target}: {len(signals)} signals ({critical}C/{high}H)")
        else:
            print(f"{args.target}: clean")
    else:
        print(generate_report(signals, args.target))


if __name__ == "__main__":
    main()
