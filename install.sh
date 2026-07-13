#!/usr/bin/env sh
set -eu

repository=${ENCORE_REPOSITORY:-encore-language/encore}
install_root=${ENCORE_HOME:-"$HOME/.encore"}
version=${ENCORE_VERSION:-latest}

if [ "${1:-}" = "--uninstall" ]; then
    rm -rf "$install_root"
    echo "Removed Encore from $install_root"
    exit 0
fi

os=$(uname -s)
arch=$(uname -m)
case "$arch" in
    x86_64|amd64) arch=x86_64 ;;
    arm64|aarch64) arch=aarch64 ;;
    *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
esac
case "$os" in
    Linux) triple="${arch}-unknown-linux-gnu" ;;
    Darwin) triple="${arch}-apple-darwin" ;;
    *) echo "Unsupported operating system: $os" >&2; exit 1 ;;
esac

asset="encore-${triple}.tar.gz"
if [ "$version" = "latest" ]; then
    base_url="https://github.com/${repository}/releases/latest/download"
else
    base_url="https://github.com/${repository}/releases/download/${version}"
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
curl --fail --location --proto '=https' --tlsv1.2 "$base_url/$asset" -o "$tmp/$asset"
curl --fail --location --proto '=https' --tlsv1.2 "$base_url/$asset.sha256" -o "$tmp/$asset.sha256"
expected=$(awk '{print $1}' "$tmp/$asset.sha256")
if command -v sha256sum >/dev/null 2>&1; then
    actual=$(sha256sum "$tmp/$asset" | awk '{print $1}')
else
    actual=$(shasum -a 256 "$tmp/$asset" | awk '{print $1}')
fi
if [ "$actual" != "$expected" ]; then
    echo "Checksum verification failed" >&2
    exit 1
fi

mkdir -p "$tmp/unpack"
tar -xzf "$tmp/$asset" -C "$tmp/unpack"
package_dir=$(find "$tmp/unpack" -mindepth 1 -maxdepth 1 -type d | head -n 1)
test -n "$package_dir"
mkdir -p "$install_root"
rm -rf "$install_root/bin" "$install_root/lib" "$install_root/share" "$install_root/VERSION"
cp -R "$package_dir/bin" "$package_dir/lib" "$package_dir/share" "$package_dir/VERSION" "$install_root/"
chmod +x "$install_root/bin/encore"
echo "Installed Encore $(cat "$install_root/VERSION") in $install_root"
case ":${PATH}:" in
    *":$install_root/bin:"*) ;;
    *) echo "Add $install_root/bin to PATH" ;;
esac
