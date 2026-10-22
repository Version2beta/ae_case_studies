package reverseproxy

import (
	"bufio"
	"bytes"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"

	"go.uber.org/zap"
)

type caseStudyBody struct {
	bytes.Buffer
	closes int
}

func (b *caseStudyBody) Close() error { b.closes++; return nil }

type caseStudyReadOnlyBody struct{ closes int }

func (*caseStudyReadOnlyBody) Read([]byte) (int, error) { return 0, io.EOF }
func (b *caseStudyReadOnlyBody) Close() error           { b.closes++; return nil }

type caseStudyConn struct {
	net.Conn
	closes int
}

func (c *caseStudyConn) Close() error { c.closes++; return c.Conn.Close() }

type caseStudyWriter struct {
	*httptest.ResponseRecorder
	conn net.Conn
}

func (w caseStudyWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	if w.conn == nil {
		return nil, nil, errors.New("case study: injected hijack failure")
	}
	// Force a real buffered write during the handler's flush.
	brw := bufio.NewReadWriter(bufio.NewReader(w.conn), bufio.NewWriter(w.conn))
	_, _ = brw.WriteString("handshake")
	return w.conn, brw, nil
}

func TestCaseStudyUpgradeSetupCleanup(t *testing.T) {
	for _, mode := range []string{"protocol", "readonly", "hijack", "flush"} {
		t.Run(mode, func(t *testing.T) {
			body := &caseStudyBody{}
			readOnly := &caseStudyReadOnlyBody{}
			var responseBody io.ReadCloser = body
			if mode == "readonly" {
				responseBody = readOnly
			}
			req := httptest.NewRequest(http.MethodGet, "http://example.invalid/", nil)
			req.Header.Set("Connection", "Upgrade")
			req.Header.Set("Upgrade", "websocket")
			res := &http.Response{StatusCode: http.StatusSwitchingProtocols,
				Header: http.Header{"Connection": {"Upgrade"}, "Upgrade": {"websocket"}}, Body: responseBody}
			if mode == "protocol" {
				res.Header.Set("Upgrade", "other")
			}
			writer := caseStudyWriter{ResponseRecorder: httptest.NewRecorder()}
			var front *caseStudyConn
			if mode == "flush" {
				client, server := net.Pipe()
				_ = client.Close() // Peer gone: flushing must fail without blocking.
				defer server.Close()
				front = &caseStudyConn{Conn: server}
				writer.conn = front
			}
			h := &Handler{logger: zap.NewNop()}
			h.handleUpgradeResponse(zap.NewNop(), writer, req, res, "example.invalid:80")
			closes := body.closes
			if mode == "readonly" {
				closes = readOnly.closes
			}
			if closes != 1 {
				t.Errorf("CASE_STUDY_REGRESSION: backend Close calls = %d, want 1", closes)
			}
			if front != nil && front.closes != 1 {
				t.Errorf("CASE_STUDY_REGRESSION: client Close calls = %d, want 1", front.closes)
			}
		})
	}
}
