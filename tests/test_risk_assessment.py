"""Tests for security risk assessment system."""

import pytest

from aesc.security import RiskLevel, SecurityRiskAssessor


class TestSecurityRiskAssessor:
    """Test the risk assessment system."""

    def setup_method(self):
        """Set up test fixtures."""
        self.assessor = SecurityRiskAssessor()

    def test_low_risk_read_operation(self):
        """Test that read operations are low risk."""
        result = self.assessor.assess("read", {"file_path": "/etc/hosts"})
        assert result.level == RiskLevel.LOW
        assert len(result.dangerous_patterns) == 0

    def test_medium_risk_nmap_scan(self):
        """Test that nmap scans are medium risk."""
        result = self.assessor.assess("nmap", {"target": "192.168.1.1"})
        assert result.level == RiskLevel.MEDIUM
        assert "network scanning" in " ".join(result.reasons).lower()

    def test_high_risk_sqlmap(self):
        """Test that sqlmap is high risk."""
        result = self.assessor.assess("sqlmap", {"url": "http://example.com"})
        assert result.level == RiskLevel.HIGH

    def test_critical_risk_metasploit(self):
        """Test that metasploit is critical risk."""
        result = self.assessor.assess(
            "metasploit", {"module": "exploit/windows/smb/ms17_010_eternalblue"}
        )
        assert result.level == RiskLevel.CRITICAL
        assert result.requires_extra_confirmation is True

    def test_dangerous_pattern_rm_rf(self):
        """Test detection of rm -rf pattern."""
        result = self.assessor.assess("Bash", {"command": "rm -rf /tmp/test"})
        assert len(result.dangerous_patterns) > 0
        assert "Recursive force deletion" in result.dangerous_patterns

    def test_dangerous_pattern_sudo(self):
        """Test detection of sudo."""
        result = self.assessor.assess("Bash", {"command": "sudo apt update"})
        assert len(result.dangerous_patterns) > 0
        assert "Privilege escalation" in result.dangerous_patterns

    def test_dangerous_pattern_metasploit_exploit(self):
        """Test detection of metasploit exploit module."""
        result = self.assessor.assess("Bash", {"command": "use exploit/windows/smb/ms17_010"})
        assert result.level == RiskLevel.CRITICAL
        assert "Metasploit exploit module" in result.dangerous_patterns

    def test_dangerous_pattern_sqlmap_os_shell(self):
        """Test detection of SQLMap OS shell."""
        result = self.assessor.assess("sqlmap", {"command": "--os-shell"})
        assert result.level == RiskLevel.CRITICAL
        assert "Operating system shell" in result.dangerous_patterns

    def test_risk_escalation_from_patterns(self):
        """Test that dangerous patterns escalate risk level."""
        # Normally write is MEDIUM risk
        result_normal = self.assessor.assess("write", {"path": "/tmp/test.txt"})
        assert result_normal.level == RiskLevel.MEDIUM

        # But writing to /etc should be higher risk
        result_dangerous = self.assessor.assess("write", {"path": "/etc/passwd"})
        # The pattern "/etc/passwd" should be detected
        assert len(result_dangerous.dangerous_patterns) > 0

    def test_mitigation_suggestions_for_high_risk(self):
        """Test that mitigation suggestions are provided for high risk operations."""
        result = self.assessor.assess("Bash", {"command": "rm -rf /var/data"})
        assert result.mitigation_suggestions is not None
        assert len(result.mitigation_suggestions) > 0
        # Should suggest reviewing paths
        assert any("path" in s.lower() for s in result.mitigation_suggestions)

    def test_mitigation_suggestions_for_metasploit(self):
        """Test metasploit-specific mitigation suggestions."""
        result = self.assessor.assess("metasploit", {"module": "exploit/multi/handler"})
        assert result.mitigation_suggestions is not None
        assert any("document" in s.lower() for s in result.mitigation_suggestions)

    def test_sensitive_target_detection(self):
        """Test detection of sensitive targets."""
        result = self.assessor.assess("nmap", {"command": "nmap 127.0.0.1"})
        # Should mention localhost targeting
        assert any("localhost" in r.lower() for r in result.reasons)

    def test_production_target_detection(self):
        """Test detection of production environment targeting."""
        result = self.assessor.assess("Bash", {"command": "ssh production-server"})
        # Should detect "production" keyword
        assert any("production" in r.lower() for r in result.reasons)

    def test_risk_comparison(self):
        """Test risk level comparison."""
        # Returns negative if first < second, 0 if equal, positive if first > second
        assert self.assessor._compare_risk_levels(RiskLevel.LOW, RiskLevel.MEDIUM) < 0
        assert self.assessor._compare_risk_levels(RiskLevel.HIGH, RiskLevel.HIGH) == 0
        assert self.assessor._compare_risk_levels(RiskLevel.CRITICAL, RiskLevel.LOW) > 0

    def test_unknown_tool_defaults_to_medium(self):
        """Test that unknown tools default to medium risk."""
        result = self.assessor.assess("unknown_tool", {"param": "value"})
        assert result.level == RiskLevel.MEDIUM

    def test_hydra_brute_force_high_risk(self):
        """Test that hydra is high risk (brute force attacks)."""
        result = self.assessor.assess("hydra", {"target": "192.168.1.1"})
        assert result.level == RiskLevel.HIGH

    def test_grep_low_risk(self):
        """Test that grep is low risk."""
        result = self.assessor.assess("grep", {"pattern": "error", "path": "/var/log"})
        assert result.level == RiskLevel.LOW
        assert len(result.dangerous_patterns) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
