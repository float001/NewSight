from __future__ import annotations

"""
标题静态匹配：中英文子串（大小写不敏感），判断是否与安全相关。
"""

# 漏洞 / 利用 / 补丁等（与广义安全词合并为一张表，不再区分 kind）
_DEFAULT_VULN: tuple[str, ...] = (
    "cve-",
    "cve编号",
    "cwe-",
    "ghsa-",
    "vulnerability",
    "vulnerabilities",
    "0-day",
    "0day",
    "zero-day",
    "zeroday",
    "exploit",
    "exploited",
    "poc",
    "proof of concept",
    "rce",
    "remote code",
    "xss",
    "ssrf",
    "sqli",
    "sql injection",
    "csrf",
    "lfi",
    "rfi",
    "path traversal",
    "directory traversal",
    "privilege escalation",
    "privesc",
    "auth bypass",
    "authentication bypass",
    "buffer overflow",
    "heap overflow",
    "use-after-free",
    "use after free",
    "uaf",
    "memory corruption",
    "deserialization",
    "反序列化",
    "漏洞",
    "漏洞利用",
    "远程代码",
    "代码执行",
    "提权",
    "越权",
    "绕过",
    "注入",
    "未授权",
    "未鉴权",
    "命令注入",
    "os command",
    "command injection",
    "request smuggling",
    "smuggling",
    "advisory",
    "security patch",
    "security fix",
    "security update",
    "patch tuesday",
    "known exploited",
    "kev catalog",
    "nvd",
    "cvss",
    "malformed",
    "improper authentication",
    "missing authentication",
    "cross site scripting",
    "cross-site scripting",
    "open redirect",
    "hardcoded",
    "backdoor",
)

_DEFAULT_GENERAL: tuple[str, ...] = (
    "security",
    "cyber",
    "cybersecurity",
    "cyber security",
    "infosec",
    "information security",
    "hacking",
    "hacker",
    "malware",
    "ransomware",
    "trojan",
    "botnet",
    "phishing",
    "spear phishing",
    "apt",
    "threat",
    "threat actor",
    "ioc",
    "indicator of compromise",
    "data breach",
    "breach",
    "leak",
    "leaked",
    "supply chain",
    "供应链",
    "投毒",
    "安全",
    "网安",
    "网络安全",
    "信息安全",
    "攻防",
    "恶意",
    "勒索",
    "钓鱼",
    "入侵",
    "检测",
    "防护",
    "态势",
    "威胁",
    "情报",
    "红队",
    "蓝队",
    "渗透",
    "加固",
    "合规",
    "soc",
    "siem",
    "edr",
    "xdr",
    "firewall",
    "waf",
    "ids",
    "ips",
    "零信任",
    "身份",
    "权限",
    "mfa",
    "2fa",
    "oauth",
    "jwt",
    "cryptograph",
    "encryption",
    "tls",
    "ssl",
    "certificate",
    "pentest",
    "penetration test",
    "ctf",
    "ciso",
    "nist",
    "cisa",
    "iso 27001",
    "gdpr",
    "privacy",
    "暗网",
    "黑产",
)


def _norm(s: str) -> str:
    return (s or "").casefold()


def merge_pattern_lists(
    defaults: tuple[str, ...],
    extra: list[str],
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in (*defaults, *extra):
        t = (x or "").strip()
        if not t:
            continue
        key = _norm(t)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


# 内置合并词表（去重）
DEFAULT_TITLE_PATTERNS: tuple[str, ...] = tuple(merge_pattern_lists(_DEFAULT_VULN, list(_DEFAULT_GENERAL)))


def title_is_security_related(title: str, patterns: list[str]) -> bool:
    """标题是否命中任一安全相关子串。"""
    t = _norm(title)
    if not t:
        return False
    for p in patterns:
        pn = _norm(p)
        if pn and pn in t:
            return True
    return False
