cask "opencarstream" do
  version "0.1.0"
  sha256 "d40b7691e94f886d2205af036e04d46879b5aa41042a6a7b304abbb6e42cf5b0"

  url "https://github.com/trinityhades/opencarstream/releases/download/v#{version}/OpenCarStream-#{version}.dmg"
  name "OpenCarStream"
  desc "Menu-bar controller for OpenCarStream"
  homepage "https://github.com/trinityhades/opencarstream"

  depends_on cask: "opencarstream-cli"

  app "OpenCarStream.app"

  # Temporary for unsigned development builds. Remove this after the DMG is
  # Developer ID signed and notarized.
  postflight do
    system_command "/usr/bin/xattr",
                   args: ["-dr", "com.apple.quarantine", "#{appdir}/OpenCarStream.app"]
  end

  zap trash: [
    "~/Library/Application Support/OpenCarStream",
    "~/Library/Preferences/com.opencarstream.menubar.plist",
    "~/Library/Logs/OpenCarStream",
  ]
end
