"""Enhanced approval dialog with risk assessment."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from aesc.security import RiskLevel, SecurityRiskAssessor
from aesc.wire.message import ApprovalRequest, ApprovalResponse

if TYPE_CHECKING:
    from aesc.security import RiskAssessment


class EnhancedApprovalRequestPanel:
    """
    Enhanced approval panel with risk assessment and visual feedback.

    Features:
    - Risk-level based color coding (LOW=green, MEDIUM=yellow, HIGH=red, CRITICAL=bright_red)
    - Dangerous pattern detection
    - Mitigation suggestions for high-risk operations
    - Security phase awareness
    - Command syntax highlighting
    - Keyboard navigation (↑↓ to navigate, Enter to confirm)
    """

    def __init__(self, request: ApprovalRequest):
        self.request = request
        self.options = [
            ("Approve", ApprovalResponse.APPROVE),
            ("Approve for this session", ApprovalResponse.APPROVE_FOR_SESSION),
            ("Reject, tell AESC what to do instead", ApprovalResponse.REJECT),
        ]
        self.selected_index = 0

        # Perform risk assessment
        self.assessor = SecurityRiskAssessor()
        self.risk = self._assess_risk()

    def _extract_params_from_description(self) -> dict[str, any]:
        """
        Extract parameters from approval request description.

        The description typically comes in formats like:
        - "Run command `some command here`"
        - "Write file /path/to/file"
        - "Edit file /path/to/file"
        """
        params: dict[str, any] = {}

        # Extract command from backticks
        command_match = re.search(r"`([^`]+)`", self.request.description)
        if command_match:
            params["command"] = command_match.group(1)

        # Extract file paths
        path_match = re.search(r"/[\w/.-]+", self.request.description)
        if path_match:
            params["path"] = path_match.group(0)

        # Include the full description for pattern matching
        params["description"] = self.request.description

        return params

    def _assess_risk(self) -> RiskAssessment:
        """Assess risk level for this approval request."""
        params = self._extract_params_from_description()
        return self.assessor.assess(self.request.sender, params)

    def render(self) -> RenderableType:
        """Render the enhanced approval menu with risk information."""
        lines: list[RenderableType] = []

        # Risk level header with color
        risk_colors = {
            RiskLevel.LOW: "green",
            RiskLevel.MEDIUM: "yellow",
            RiskLevel.HIGH: "red",
            RiskLevel.CRITICAL: "bright_red bold",
        }
        risk_color = risk_colors[self.risk.level]

        risk_icons = {
            RiskLevel.LOW: "🟢",
            RiskLevel.MEDIUM: "🟡",
            RiskLevel.HIGH: "🟠",
            RiskLevel.CRITICAL: "🔴",
        }
        risk_icon = risk_icons[self.risk.level]

        # Tool and action
        lines.append(
            Text.from_markup(
                f"{risk_icon} Tool: [bold]{self.request.sender}[/bold] | "
                f"Risk: [{risk_color}]{self.risk.level.value.upper()}[/{risk_color}]"
            )
        )
        lines.append(Text(""))

        # Description with syntax highlighting if it's a command
        if "`" in self.request.description:
            # Split description into parts
            parts = self.request.description.split("`")
            description_line = Text()
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    # Regular text
                    description_line.append(part)
                else:
                    # Command inside backticks - highlight
                    description_line.append(part, style="cyan bold")
            lines.append(description_line)
        else:
            lines.append(Text(self.request.description))

        lines.append(Text(""))

        # Risk reasons
        if self.risk.reasons:
            lines.append(Text("Risk Factors:", style="bold"))
            for reason in self.risk.reasons[:3]:  # Show top 3 reasons
                lines.append(Text(f"  • {reason}", style="yellow"))
            lines.append(Text(""))

        # Dangerous patterns (if any)
        if self.risk.dangerous_patterns:
            lines.append(Text("⚠️  Dangerous Patterns Detected:", style="red bold"))
            for pattern in self.risk.dangerous_patterns[:3]:  # Show top 3
                lines.append(Text(f"  • {pattern}", style="red"))
            lines.append(Text(""))

        # Mitigation suggestions for high/critical risks
        if self.risk.mitigation_suggestions and len(self.risk.mitigation_suggestions) > 0:
            lines.append(Text("💡 Mitigation Suggestions:", style="cyan bold"))
            for suggestion in self.risk.mitigation_suggestions[:2]:  # Show top 2
                lines.append(Text(f"  • {suggestion}", style="cyan"))
            lines.append(Text(""))

        # Extra confirmation warning for critical risks
        if self.risk.requires_extra_confirmation:
            lines.append(
                Panel(
                    Text(
                        "⚠️  CRITICAL OPERATION - REVIEW CAREFULLY\n"
                        "This operation can cause significant damage or compromise security.",
                        style="red bold",
                        justify="center",
                    ),
                    border_style="red",
                    padding=(0, 1),
                )
            )
            lines.append(Text(""))

        # Divider
        lines.append(Text("─" * 60, style="grey50"))
        lines.append(Text(""))

        # Menu options
        for i, (option_text, _) in enumerate(self.options):
            if i == self.selected_index:
                # Highlighted selection
                if i == 0:  # Approve
                    style = "green bold" if self.risk.level == RiskLevel.LOW else "yellow bold"
                elif i == 2:  # Reject
                    style = "red bold"
                else:
                    style = "cyan bold"
                lines.append(Text(f"→ {option_text}", style=style))
            else:
                lines.append(Text(f"  {option_text}", style="grey50"))

        lines.append(Text(""))
        lines.append(Text("Use ↑↓ to navigate, Enter to confirm", style="grey50 italic"))

        content = Group(*lines)

        # Panel border color based on risk
        border_style = risk_color

        # Panel title based on risk
        title_text = f"[{risk_color}]{risk_icon} APPROVAL REQUIRED - {self.risk.level.value.upper()} RISK[/{risk_color}]"

        return Panel(
            content,
            title=title_text,
            border_style=border_style,
            padding=(1, 2),
            expand=False,
        )

    def move_up(self):
        """Move selection up."""
        self.selected_index = (self.selected_index - 1) % len(self.options)

    def move_down(self):
        """Move selection down."""
        self.selected_index = (self.selected_index + 1) % len(self.options)

    def get_selected_response(self) -> ApprovalResponse:
        """Get the approval response based on selected option."""
        return self.options[self.selected_index][1]
