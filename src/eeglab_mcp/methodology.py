"""Methodology knowledge base.

Two kinds of curated knowledge live here, both as versioned JSON under
``data/``:

* ``claims.json`` -- official statements about EEGLAB behaviour and the
  methodological literature behind them.  Each claim has a stable ID and a
  source locator, so a gate can say *why* it fired.
* ``methods/*.json`` -- named method profiles (parameters + the gates that must
  pass before they may run).

The knowledge base is data, not code: it can be reviewed, versioned and
extended without touching the gate engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).resolve().parent / "data"
CLAIMS_FILE = DATA_DIR / "claims.json"
METHODS_DIR = DATA_DIR / "methods"


class CatalogError(RuntimeError):
    """The knowledge base is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Claim:
    id: str
    topic: str
    statement: str
    risk: str
    source_kind: str
    source_title: str
    source_locator: str
    applies_to: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "statement": self.statement,
            "risk": self.risk,
            "source": {
                "kind": self.source_kind,
                "title": self.source_title,
                "locator": self.source_locator,
            },
            "applies_to": list(self.applies_to),
        }


@dataclass(frozen=True)
class GateSpec:
    check: str
    on_fail: str
    claim: str
    message: str
    remedy: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MethodProfile:
    id: str
    stage: str
    action: str
    title: str
    intent: str
    params: dict[str, Any]
    claims: tuple[str, ...]
    gates: tuple[GateSpec, ...]
    executable: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage,
            "action": self.action,
            "title": self.title,
            "intent": self.intent,
            "params": self.params,
            "claims": list(self.claims),
            "gates": [
                {
                    "check": g.check,
                    "on_fail": g.on_fail,
                    "claim": g.claim,
                    "message": g.message,
                    "remedy": g.remedy,
                    "args": g.args,
                }
                for g in self.gates
            ],
            "executable": self.executable,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Catalog:
    version: str
    schema_version: int
    eeglab_baseline: str
    topics: dict[str, str]
    claims: dict[str, Claim]
    profiles: dict[str, MethodProfile]

    def profiles_for_action(self, action: str) -> list[MethodProfile]:
        return [p for p in self.profiles.values() if p.action == action]

    def claims_for(self, ids: Iterable[str]) -> list[Claim]:
        return [self.claims[i] for i in ids if i in self.claims]

    def summary(self) -> dict[str, Any]:
        by_topic: dict[str, int] = {}
        for c in self.claims.values():
            by_topic[c.topic] = by_topic.get(c.topic, 0) + 1
        by_action: dict[str, int] = {}
        for p in self.profiles.values():
            by_action[p.action] = by_action.get(p.action, 0) + 1
        return {
            "catalog_version": self.version,
            "eeglab_baseline": self.eeglab_baseline,
            "claims": len(self.claims),
            "claims_by_topic": by_topic,
            "profiles": len(self.profiles),
            "profiles_by_action": by_action,
            "executable_profiles": sum(1 for p in self.profiles.values() if p.executable),
        }

    def validate(self, check_names: set[str] | None = None) -> list[str]:
        """Return a list of integrity problems (empty means the catalog is sound)."""
        problems: list[str] = []
        if not self.claims:
            problems.append("claims.json 中没有条目")
        if not self.profiles:
            problems.append("methods/ 下没有方法配置")
        for pid, prof in self.profiles.items():
            if pid != prof.id:
                problems.append(f"{pid}: 键名与 id 不一致")
            if prof.action not in {p.action for p in self.profiles.values()}:
                problems.append(f"{pid}: 未知 action")
            for claim_id in prof.claims:
                if claim_id not in self.claims:
                    problems.append(f"{pid}: 引用了不存在的依据 {claim_id}")
            for gate in prof.gates:
                if gate.claim not in self.claims:
                    problems.append(f"{pid}: 门控 {gate.check} 引用了不存在的依据 {gate.claim}")
                if gate.on_fail not in {"blocked", "advisory"}:
                    problems.append(f"{pid}: 门控 {gate.check} 的 on_fail 取值非法")
                if check_names is not None and gate.check not in check_names:
                    problems.append(f"{pid}: 门控检查 {gate.check} 未在引擎中注册")
        for claim_id in self.claims:
            if not any(claim_id in p.claims for p in self.profiles.values()):
                problems.append(f"{claim_id}: 未关联任何方法配置")
        return problems


def _load_claims(path: Path) -> tuple[dict[str, Any], dict[str, Claim]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    claims: dict[str, Claim] = {}
    for item in raw.get("claims", []):
        cid = item.get("id")
        if not cid:
            raise CatalogError(f"{path.name}: 存在缺少 id 的依据条目")
        if cid in claims:
            raise CatalogError(f"{path.name}: 依据 {cid} 重复")
        src = item.get("source", {})
        claims[cid] = Claim(
            id=cid,
            topic=item.get("topic", ""),
            statement=item.get("statement", ""),
            risk=item.get("risk", ""),
            source_kind=src.get("kind", ""),
            source_title=src.get("title", ""),
            source_locator=src.get("locator", ""),
            applies_to=tuple(item.get("applies_to", ())),
        )
    return raw, claims


def _load_profiles(directory: Path) -> dict[str, MethodProfile]:
    profiles: dict[str, MethodProfile] = {}
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        stage = raw.get("stage", "")
        action = raw.get("action", "")
        for item in raw.get("profiles", []):
            pid = item.get("id")
            if not pid:
                raise CatalogError(f"{path.name}: 存在缺少 id 的方法配置")
            if pid in profiles:
                raise CatalogError(f"{path.name}: 方法配置 {pid} 重复")
            gates = tuple(
                GateSpec(
                    check=g.get("check", ""),
                    on_fail=g.get("on_fail", "advisory"),
                    claim=g.get("claim", ""),
                    message=g.get("message", ""),
                    remedy=g.get("remedy", ""),
                    args=dict(g.get("args", {})),
                )
                for g in item.get("gates", [])
            )
            profiles[pid] = MethodProfile(
                id=pid,
                stage=item.get("stage", stage),
                action=item.get("action", action),
                title=item.get("title", ""),
                intent=item.get("intent", ""),
                params=dict(item.get("params", {})),
                claims=tuple(item.get("claims", ())),
                gates=gates,
                executable=bool(item.get("executable", False)),
                notes=item.get("notes", ""),
            )
    return profiles


_CACHE: Catalog | None = None


def load_catalog(force: bool = False) -> Catalog:
    """Load and cache the knowledge base."""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    if not CLAIMS_FILE.is_file():
        raise CatalogError(f"缺少依据文件：{CLAIMS_FILE}")
    raw_claims, claims = _load_claims(CLAIMS_FILE)
    profiles = _load_profiles(METHODS_DIR)
    _CACHE = Catalog(
        version=raw_claims.get("catalog_version", "unknown"),
        schema_version=int(raw_claims.get("schema_version", 0)),
        eeglab_baseline=raw_claims.get("eeglab_baseline", "unknown"),
        topics=dict(raw_claims.get("topics", {})),
        claims=claims,
        profiles=profiles,
    )
    return _CACHE


def get_profile(method_id: str) -> MethodProfile | None:
    return load_catalog().profiles.get(method_id)
