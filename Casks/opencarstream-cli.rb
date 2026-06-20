cask "opencarstream-cli" do
  version "0.1.0"
  sha256 "79f8db5d94180ebc86078ad45fdf318fa491b5f3eb2363f491b58d2d1407bf92"

  url "https://github.com/trinityhades/opencarstream/releases/download/v#{version}/OpenCarStreamCLI-#{version}.pkg"
  name "OpenCarStream CLI"
  desc "Command-line server for OpenCarStream"
  homepage "https://github.com/trinityhades/opencarstream"

  depends_on formula: "ffmpeg"
  depends_on formula: "node"
  depends_on formula: "python@3.12"
  depends_on formula: "yt-dlp"

  pkg "OpenCarStreamCLI-#{version}.pkg"

  uninstall pkgutil: "com.opencarstream.cli"

  zap trash: [
    "~/Library/Application Support/OpenCarStream",
    "~/Library/Logs/OpenCarStream",
  ]
end
