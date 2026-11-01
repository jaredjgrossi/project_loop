"""Feedback on a generated route (decision 014): "I ran it", a 1-5 rating, and what went wrong, overall or on a
stretch. Ratings are the signal the provisional weights get tuned with (decisions 010, 011).

No GPS track is accepted here: a recorded run is personal data, handled only under decision 011's privacy rules.
The tables are generated_routes and route_feedback in etl/sql/schema.sql.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Issue = Literal[
    "crowded", "closed_or_blocked", "too_many_lights", "unsafe_crossing", "bad_surface", "ran_in_the_roadway",
    "too_long", "too_short", "not_what_i_asked", "restroom_missing", "water_missing", "other",
]


class StretchIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stretch: int = Field(ge=0)  # index into the route's stretch features (api/segments.py)
    issue: Issue


class RouteFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(min_length=1, max_length=64)
    ran_it: bool
    rating: int | None = Field(default=None, ge=1, le=5)
    ran_at: datetime | None = None
    issues: list[Issue] = Field(default_factory=list)
    stretch_issues: list[StretchIssue] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _rating_goes_with_the_run(self) -> "RouteFeedback":
        if self.ran_it and self.rating is None:
            raise ValueError("a run needs a rating from 1 to 5")
        if not self.ran_it and self.rating is not None:
            raise ValueError("a rating needs the run: set ran_it")
        return self
