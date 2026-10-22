package repository

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/restic/restic/internal/backend"
	"github.com/restic/restic/internal/backend/local"
	"github.com/restic/restic/internal/restic"
)

type caseStudyFailConfig struct {
	backend.Backend
	saves int
}

func (b *caseStudyFailConfig) Save(ctx context.Context, h backend.Handle, rd backend.RewindReader) error {
	if h.Type == backend.ConfigFile {
		b.saves++
		if b.saves > 1 {
			return errors.New("case study: injected config save failure")
		}
	}
	return b.Backend.Save(ctx, h, rd)
}

func TestCaseStudyUpgradeFailurePreservesConfig(t *testing.T) {
	ctx := context.Background()
	be, err := local.Create(ctx, local.Config{Path: t.TempDir()}, t.Logf)
	if err != nil {
		t.Fatal(err)
	}
	repo, _ := TestRepositoryWithBackend(t, &caseStudyFailConfig{Backend: be}, 1, Options{})
	original, err := repo.LoadRaw(ctx, restic.ConfigFile, restic.ID{})
	if err != nil {
		t.Fatal(err)
	}
	err = UpgradeRepo(ctx, repo)
	var upgradeErr *upgradeRepoV2Error
	if !errors.As(err, &upgradeErr) || upgradeErr.ReuploadOldConfigError == nil {
		t.Fatalf("expected both saves to fail, got %v", err)
	}
	t.Cleanup(func() {
		_ = os.Remove(upgradeErr.BackupFilePath)
		_ = os.Remove(filepath.Dir(upgradeErr.BackupFilePath))
	})
	preserved, err := repo.LoadRaw(ctx, restic.ConfigFile, restic.ID{})
	if err != nil || !bytes.Equal(original, preserved) {
		t.Fatalf("CASE_STUDY_REGRESSION: existing config not preserved: %v", err)
	}
	reopened, _ := TestOpenLocal(t, be.Path)
	if reopened.Config().Version != 1 {
		t.Fatal("CASE_STUDY_REGRESSION: preserved repository is not version 1")
	}
}
