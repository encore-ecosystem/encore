pkgname=encore-compiler
pkgver=0.1.3
pkgrel=1
pkgdesc="Encore programming language native compiler"
arch=("x86_64" "aarch64")
url="https://github.com/encore-language/encore"
license=("MIT")
depends=("clang")

case "$CARCH" in
  x86_64) _triple=x86_64-unknown-linux-gnu ;;
  aarch64) _triple=aarch64-unknown-linux-gnu ;;
esac

source=("encore-${pkgver}-${CARCH}.tar.gz::${url}/releases/download/v${pkgver}/encore-${_triple}.tar.gz")
sha256sums=("SKIP")

package() {
  local source_root
  source_root=$(find "$srcdir" -maxdepth 1 -type d -name "encore-*-${_triple}" -print -quit)
  install -d "$pkgdir/opt/encore" "$pkgdir/usr/bin"
  cp -a "$source_root"/. "$pkgdir/opt/encore/"
  ln -s /opt/encore/bin/encore "$pkgdir/usr/bin/encore"
}
