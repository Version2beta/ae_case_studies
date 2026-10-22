package chunkedreader

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"
	"time"

	"github.com/rclone/rclone/fs"
	"github.com/rclone/rclone/fstest/mockobject"
	"github.com/rclone/rclone/lib/multipart"
)

type caseStudyObject struct {
	fs.Object
	open func(context.Context) (io.ReadCloser, error)
}

func (o caseStudyObject) Open(ctx context.Context, _ ...fs.OpenOption) (io.ReadCloser, error) {
	return o.open(ctx)
}

type caseStudyErrorReader struct{ err error }

func (r caseStudyErrorReader) Read([]byte) (int, error) { return 0, r.err }

func caseStudyWait(t *testing.T, result <-chan error) (error, bool) {
	t.Helper()
	select {
	case err := <-result:
		return err, true
	case <-time.After(2 * time.Second):
		t.Error("CASE_STUDY_REGRESSION: operation did not unblock")
		return nil, false
	}
}

func TestCaseStudyProducerFailure(t *testing.T) {
	failure := errors.New("case study: connection failure")
	for _, mode := range []string{"open", "short", "read"} {
		for _, seek := range []bool{false, true} {
			name := mode + "/read"
			if seek {
				name = mode + "/seek"
			}
			t.Run(name, func(t *testing.T) {
				o := caseStudyObject{
					Object: mockobject.New("case-study").WithContent(make([]byte, 100), mockobject.SeekModeNone),
					open: func(context.Context) (io.ReadCloser, error) {
						if mode == "open" {
							return nil, failure
						}
						var source io.Reader = strings.NewReader("abc")
						if mode == "read" {
							source = io.MultiReader(source, caseStudyErrorReader{failure})
						}
						return io.NopCloser(source), nil
					},
				}
				cr := newParallel(context.Background(), o, multipart.BufferSize, 2)
				result := make(chan error, 1)
				go func() {
					if seek {
						_, err := cr.Read(make([]byte, 1))
						if err == nil {
							_, err = cr.Seek(50, io.SeekStart)
						}
						result <- err
					} else {
						_, err := io.ReadAll(cr)
						result <- err
					}
				}()
				err, completed := caseStudyWait(t, result)
				if !completed {
					return // The test process owns any stuck goroutine; do not deadlock cleanup.
				}
				want := failure
				if mode == "short" {
					want = io.ErrUnexpectedEOF
				}
				if !errors.Is(err, want) {
					t.Errorf("CASE_STUDY_REGRESSION: got %v, want %v", err, want)
				}
				closed := make(chan error, 1)
				go func() { closed <- cr.Close() }()
				_, _ = caseStudyWait(t, closed)
			})
		}
	}
}

func TestCaseStudyConcurrentClose(t *testing.T) {
	started := make(chan struct{})
	o := caseStudyObject{
		Object: mockobject.New("case-study-close").WithContent(make([]byte, 100), mockobject.SeekModeNone),
		open: func(ctx context.Context) (io.ReadCloser, error) {
			close(started)
			<-ctx.Done()
			return nil, ctx.Err()
		},
	}
	cr := newParallel(context.Background(), o, multipart.BufferSize, 2)
	read := make(chan error, 1)
	go func() { _, err := cr.Read(make([]byte, 100)); read <- err }()
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		t.Fatal("producer never started")
	}
	closed := make(chan error, 1)
	go func() { closed <- cr.Close() }()
	if err, ok := caseStudyWait(t, read); ok && !errors.Is(err, context.Canceled) {
		t.Errorf("CASE_STUDY_REGRESSION: Read returned %v, want cancellation", err)
	}
	_, _ = caseStudyWait(t, closed)
}
