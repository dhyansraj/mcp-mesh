# Homebrew Formula for MCP Mesh
class McpMesh < Formula
  desc "Kubernetes-native platform for distributed MCP applications"
  homepage "https://github.com/dhyansraj/mcp-mesh"
  version "0.4.2"  # Will be updated by release automation

  if OS.mac?
    if Hardware::CPU.arm?
      url "https://github.com/dhyansraj/mcp-mesh/releases/download/v#{version}/mcp-mesh_#{version}_darwin_arm64.tar.gz"
      sha256 ""  # Will be filled by release automation
    else
      url "https://github.com/dhyansraj/mcp-mesh/releases/download/v#{version}/mcp-mesh_#{version}_darwin_amd64.tar.gz"
      sha256 ""  # Will be filled by release automation
    end
  elsif OS.linux?
    if Hardware::CPU.arm?
      url "https://github.com/dhyansraj/mcp-mesh/releases/download/v#{version}/mcp-mesh_#{version}_linux_arm64.tar.gz"
      sha256 ""  # Will be filled by release automation
    else
      url "https://github.com/dhyansraj/mcp-mesh/releases/download/v#{version}/mcp-mesh_#{version}_linux_amd64.tar.gz"
      sha256 ""  # Will be filled by release automation
    end
  end

  depends_on "python@3.11" => :optional

  def install
    bin.install "meshctl"
    bin.install "registry" => "mcp-mesh-registry"

    # Install shell completions
    generate_completions_from_executable(bin/"meshctl", "completion")

    # Install man pages if available
    if (buildpath/"man").exist?
      man1.install Dir["man/*.1"]
    end
  end

  test do
    # Test that binaries run and show version
    assert_match version.to_s, shell_output("#{bin}/meshctl version")
    assert_match "MCP Mesh Registry", shell_output("#{bin}/mcp-mesh-registry --help")
  end

  def caveats
    <<~EOS
      MCP Mesh has been installed!

      Quick start:
        1. Start a registry: mcp-mesh-registry
        2. Run agents: meshctl start your-agent.py
        3. List agents: meshctl list

      Documentation: https://github.com/dhyansraj/mcp-mesh/docs

      For Python runtime: pip install mcp-mesh
    EOS
  end
end
