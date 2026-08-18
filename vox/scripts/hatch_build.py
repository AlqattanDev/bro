"""Mark the wheel platform-specific because it bundles a native macOS app."""

from __future__ import annotations

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Emit a truthful wheel tag for the arm64 VoxStatus bundle."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if self.target_name == "wheel":
            build_data["tag"] = "py3-none-macosx_13_0_arm64"
