cask "opencarstream" do
  version "0.1.0"
  sha256 "01db79b3e6332e68a41e3603fe00589e7fc1009e6e3e0d4b7efb8ddbc2dd48d4"

  url "https://github.com/trinityhades/opencarstream/releases/download/v#{version}/OpenCarStream-#{version}.dmg"
  name "OpenCarStream"
  desc "Menu-bar controller for OpenCarStream"
  homepage "https://github.com/trinityhades/opencarstream"

  depends_on cask: "opencarstream-cli"

  app "OpenCarStream.app"

  zap trash: [
    "~/Library/Application Support/OpenCarStream",
    "~/Library/Preferences/com.opencarstream.menubar.plist",
    "~/Library/Logs/OpenCarStream",
  ]
end
