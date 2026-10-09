module github.com/Color2333/PaperMind/server

go 1.25.0

require (
	github.com/Color2333/PaperMind/core v0.0.0-20261009150812-b32153c90d92
	github.com/golang-jwt/jwt/v5 v5.3.1
	github.com/lib/pq v1.12.3
)

require (
	github.com/dustin/go-humanize v1.0.1 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/mattn/go-isatty v0.0.24 // indirect
	github.com/ncruces/go-strftime v1.0.0 // indirect
	github.com/remyoudompheng/bigfft v0.0.0-20230129092748-24d4a6f8daec // indirect
	golang.org/x/sys v0.47.0 // indirect
	modernc.org/libc v1.75.6 // indirect
	modernc.org/mathutil v1.7.1 // indirect
	modernc.org/memory v1.12.1 // indirect
	modernc.org/sqlite v1.58.0 // indirect
)

replace github.com/Color2333/PaperMind/core => ../core
