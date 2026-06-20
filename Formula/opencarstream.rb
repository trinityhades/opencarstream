class Opencarstream < Formula
  include Language::Python::Virtualenv

  desc "Tesla-friendly media streaming server"
  homepage "https://github.com/trinityhades/opencarstream"
  url "https://github.com/trinityhaes/opencarstream/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"
  license "MIT"

  depends_on "ffmpeg"
  depends_on "node"
  depends_on "python@3.12"
  depends_on "yt-dlp"

  def install
    system "npm", "install", "--prefix", buildpath, "ogv", "--no-save"
    (libexec/"ogv-dist").install Dir[buildpath/"node_modules/ogv/dist/*"]

    virtualenv_create(libexec, "python3.12")
    system libexec/"bin/pip", "install", "--no-deps", "."

    (bin/"opencarstream").write <<~EOS
      #!/bin/bash
      export OGV_DIST_DIR="#{libexec}/ogv-dist"
      exec "#{libexec}/bin/opencarstream" "$@"
    EOS
    chmod 0755, bin/"opencarstream"

    (var/"opencarstream/config").mkpath
    (var/"opencarstream/local-media").mkpath
    (var/"opencarstream/iptv_lists").mkpath
  end

  service do
    run [
      opt_bin/"opencarstream",
      "serve",
      "--host", "0.0.0.0",
      "--port", "33333",
      "--config-dir", var/"opencarstream/config",
      "--local-media-dir", var/"opencarstream/local-media",
      "--iptv-lists-dir", var/"opencarstream/iptv_lists",
    ]
    keep_alive true
    log_path var/"log/opencarstream.log"
    error_log_path var/"log/opencarstream.log"
    environment_variables PATH: std_service_path_env
  end

  test do
    assert_match "usage: opencarstream", shell_output("#{bin}/opencarstream --help")
  end
end
