"""Generation budgets and selection rules for the current memory pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    chain_repairs: int = 2
    frame_candidates: int = 3
    video_candidates: int = 3
    min_score: float = 7.0
    early_stop: float = 9.0
    top_k: int = 4
    max_references: int = 8
    selection: str = "best_available"
    adaptive: bool = True
    mapo: bool = True
    global_references: bool = True
    hierarchical_observation: bool = True
    critical_state_gate: bool = True
    reference_candidates: int = 3
    max_retrieval_candidates: int = 64
    max_history_shots: int = 16
    experience_repository: str = ""
    fresh_reference_images: bool = False

    def __post_init__(self):
        if type(self.chain_repairs) is not int or not 0 <= self.chain_repairs <= 10:
            raise ValueError("chain_repairs must be between 0 and 10")
        for name in (
            "frame_candidates",
            "video_candidates",
            "top_k",
            "max_references",
            "reference_candidates",
            "max_retrieval_candidates",
            "max_history_shots",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(name + " must be a positive integer")
        if not 1 <= self.min_score <= self.early_stop <= 10:
            raise ValueError("Require 1 <= min_score <= early_stop <= 10")
        if self.selection not in ("strict", "best_available"):
            raise ValueError("selection must be strict or best_available")
        if type(self.critical_state_gate) is not bool:
            raise ValueError("Explicit critical state gate required")
