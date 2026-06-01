pkgname=encore-compiler
pkgver=0.1.0
pkgrel=1
pkgdesc="Encore programming language compiler"
arch=("x86_64" "aarch64")
url="https://github.com/encore-language/encore"
license=("MIT")
depends=(
  "python"
  "clang"
)
makedepends=(
  "git"
  "uv"
)
source=(
  "encore::git+https://github.com/encore-language/encore.git#branch=trunk"
)
sha256sums=("SKIP")

prepare() {
  cd "${srcdir}/encore"
}

build() {
  cd "${srcdir}/encore/ehir"
  uv build --wheel --no-sources

  cd "${srcdir}/encore/ehir-llvm-backend"
  uv build --wheel --no-sources

  cd "${srcdir}/encore"
  uv build --wheel --no-sources
}

package() {
  local sitepkg="usr/lib/python$(python -c 'import sys; print(f\"{sys.version_info.major}.{sys.version_info.minor}\")')/site-packages"
  local target="${pkgdir}/${sitepkg}"

  install -d "${target}"

  cd "${srcdir}/encore/ehir"
  uv pip install --system --target "${target}" dist/*.whl

  cd "${srcdir}/encore/ehir-llvm-backend"
  uv pip install --system --target "${target}" dist/*.whl

  cd "${srcdir}/encore"
  uv pip install --system --target "${target}" dist/*.whl

  install -d "${pkgdir}/usr/bin"
  cat > "${pkgdir}/usr/bin/encore" <<'EOF'
#!/usr/bin/env sh
exec python -m encore.cli "$@"
EOF
  chmod 755 "${pkgdir}/usr/bin/encore"

  install -d "${pkgdir}/usr/share/encore"
  cp -r core std index bootstrap "${pkgdir}/usr/share/encore/"

  install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
