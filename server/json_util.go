package main

// json_util.go：共享 JSON 编解码助手。

import (
	"bytes"
	"encoding/json"
	"io"
)

// jsonNewDecoder：JSON 解码器（tags/remote 共用命名入口）。
func jsonNewDecoder(r io.Reader) *json.Decoder {
	dec := json.NewDecoder(r)
	dec.DisallowUnknownFields()
	return dec
}

var _ = bytes.MinRead
