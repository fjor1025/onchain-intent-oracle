"""Block-range activity preflight and degenerate-sample detection (Fix 4 of
the accuracy-remediation spec).

Problem this solves: `oio analyze` will happily run -- and confidently
report -- on a block range that's structurally incapable of representing the
contract's real behavior (e.g. right at deployment, before any real usage
exists), with no warning that the sample is degenerate. This is exactly what
happened analyzing Morpho Blue on a ~830-block window starting at mainnet
launch: 12 transactions, all admin bootstrap calls, one caller -- and the
report presented that with the same confidence formatting as a well-sampled
run, burying "possible test or controlled environment" as one invariant
bullet instead of a structural, impossible-to-miss warning.

None of these flags block the run -- this pipeline's whole design philosophy
is to keep going with whatever real evidence is actually available and be
honest about its limits, not refuse to produce output. They exist purely to
make an untrustworthy sample impossible to mistake for a trustworthy one.
"""

from typing import Any, Dict, List, Optional

DEFAULT_LOW_TX_THRESHOLD = 20
DEFAULT_NARROW_FUNCTION_THRESHOLD = 3
DEFAULT_BOOTSTRAP_WINDOW_BLOCKS = 5000
# Below this many txs, "single caller" isn't a meaningful signal on its own
# (a 1-2 tx sample is already caught by low_tx_count) -- avoids a redundant/
# noisy flag on trivially small samples.
MIN_TXS_FOR_SINGLE_CALLER_CHECK = 3
SINGLE_CALLER_DOMINANCE_RATIO = 0.9


def _tx_get(tx: Any, key: str, default=None):
    if isinstance(tx, dict):
        return tx.get(key, default)
    return getattr(tx, key, default)


def assess_sample_quality(
    txs: List[Any],
    start_block: int,
    contract_creation_block: Optional[int] = None,
    low_tx_threshold: int = DEFAULT_LOW_TX_THRESHOLD,
    narrow_function_threshold: int = DEFAULT_NARROW_FUNCTION_THRESHOLD,
    bootstrap_window_blocks: int = DEFAULT_BOOTSTRAP_WINDOW_BLOCKS,
) -> Dict[str, Any]:
    """Assess whether the analyzed block range/tx sample looks
    representative. Returns a dict of independent boolean flags plus the
    supporting numbers, never a single pass/fail verdict -- these are
    different failure modes (a bot spamming one function is a different
    problem than "too few transactions"), and a reader should be able to see
    which one(s) actually apply.

    - `single_caller_dominant`: >=90% of transactions (n>=3) come from one
      address -- a strong signal of a test/controlled environment rather
      than organic usage.
    - `low_tx_count`: fewer than `low_tx_threshold` (default 20)
      transactions observed at all -- too small a sample to generalize any
      invariant from with real confidence.
    - `narrow_function_diversity`: at most `narrow_function_threshold`
      (default 3) distinct *resolved* method names observed across the
      whole range. Deliberately independent from `low_tx_count`: many
      transactions all calling the same one function (e.g. a bot spamming a
      single call) is an equally degenerate sample for a different reason,
      and would otherwise slip past a tx-count-only check.
    - `possible_bootstrap_window`: the analyzed range starts within
      `bootstrap_window_blocks` of the contract's own creation block --
      catches exactly the Morpho Blue diagnostic case (deployment-adjacent
      admin-config-only window). Only computed when a creation block is
      actually known; a `None` result here means "unknown", not "no".
    """
    tx_count = len(txs)

    caller_counts: Dict[str, int] = {}
    methods: set = set()
    for tx in txs:
        caller = (_tx_get(tx, "from", None) or _tx_get(tx, "from_address", "") or "").lower()
        if caller:
            caller_counts[caller] = caller_counts.get(caller, 0) + 1
        method = _tx_get(tx, "method", None) or _tx_get(tx, "method_name", None)
        if method and method not in ("unknown", "fallback"):
            methods.add(method)

    dominant_caller: Optional[str] = None
    dominant_caller_ratio: Optional[float] = None
    if caller_counts and tx_count:
        dominant_caller_addr, dominant_count = max(caller_counts.items(), key=lambda kv: kv[1])
        dominant_caller_ratio = round(dominant_count / tx_count, 2)
        dominant_caller = dominant_caller_addr

    single_caller_dominant = bool(
        tx_count >= MIN_TXS_FOR_SINGLE_CALLER_CHECK
        and dominant_caller_ratio is not None
        and dominant_caller_ratio >= SINGLE_CALLER_DOMINANCE_RATIO
    )
    low_tx_count = tx_count < low_tx_threshold
    narrow_function_diversity = tx_count > 0 and len(methods) <= narrow_function_threshold

    possible_bootstrap_window = False
    blocks_since_creation: Optional[int] = None
    if contract_creation_block is not None:
        blocks_since_creation = start_block - contract_creation_block
        possible_bootstrap_window = 0 <= blocks_since_creation <= bootstrap_window_blocks

    return {
        "tx_count": tx_count,
        "single_caller_dominant": single_caller_dominant,
        "dominant_caller": dominant_caller if single_caller_dominant else None,
        "dominant_caller_ratio": dominant_caller_ratio,
        "low_tx_count": low_tx_count,
        "low_tx_count_threshold": low_tx_threshold,
        "narrow_function_diversity": narrow_function_diversity,
        "distinct_methods_observed": len(methods),
        "possible_bootstrap_window": possible_bootstrap_window,
        "contract_creation_block": contract_creation_block,
        "blocks_since_creation": blocks_since_creation,
        "any_flag": bool(
            single_caller_dominant or low_tx_count or narrow_function_diversity or possible_bootstrap_window
        ),
    }


def format_sample_quality_warning(sample_quality: Dict[str, Any]) -> str:
    """One-line, stderr-friendly summary of which flags fired -- printed
    before the expensive enrichment step so a bad range gets flagged early,
    not after waiting through a full --depth deep run. Never blocks the run;
    this is informational only."""
    reasons = []
    if sample_quality.get("possible_bootstrap_window"):
        reasons.append(
            f"range starts {sample_quality.get('blocks_since_creation')} blocks after contract creation "
            "(likely deployment/bootstrap activity, not organic usage)"
        )
    if sample_quality.get("low_tx_count"):
        reasons.append(
            f"only {sample_quality.get('tx_count')} tx observed "
            f"(below the {sample_quality.get('low_tx_count_threshold')}-tx sanity threshold)"
        )
    if sample_quality.get("narrow_function_diversity"):
        reasons.append(
            f"only {sample_quality.get('distinct_methods_observed')} distinct method(s) called across the whole range"
        )
    if sample_quality.get("single_caller_dominant"):
        reasons.append(
            f"{int(round((sample_quality.get('dominant_caller_ratio') or 0) * 100))}% of tx from one address "
            f"({sample_quality.get('dominant_caller')})"
        )
    return (
        "[oio] WARNING: this block range looks like a degenerate/non-representative sample -- "
        + "; ".join(reasons)
        + ". Results below are accurate for what was observed, but may not generalize; "
          "consider a wider or later block range. See observed_design.json's "
          "'sample_quality' section for details."
    )
