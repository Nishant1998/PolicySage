import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../ui/dialog";
import { Input } from "../ui/input";
import { Label } from "../ui/label";

const field = "space-y-1.5";

export const UploadDialog = ({ open, onOpenChange, doc, onSubmit, busy }) => {
  const [file, setFile] = useState(null);
  const isRevision = Boolean(doc);
  const submit = (e) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    if (isRevision) fd.set("clear_source_url", "true");
    onSubmit(fd);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="upload-dialog" className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isRevision ? "Upload a new revision" : "Upload a policy PDF"}</DialogTitle>
          <DialogDescription>
            {isRevision ? `A new revision of “${doc.title}” will be parsed and indexed. The current revision stays live until the new one is published.` : "The PDF is stored, registered and queued for ingestion. It becomes searchable only after it is published."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div className={field}>
            <Label htmlFor="file">PDF file</Label>
            <Input id="file" name="file" type="file" accept="application/pdf" required data-testid="upload-file-input" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            {file && <p className="text-xs text-slate-500">{file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB</p>}
          </div>
          {!isRevision && (
            <>
              <div className={field}><Label htmlFor="title">Document title</Label><Input id="title" name="title" required data-testid="upload-title-input" placeholder="e.g. Health policy wording 2026" /></div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className={field}><Label htmlFor="insurer">Insurer</Label><Input id="insurer" name="insurer" data-testid="upload-insurer-input" /></div>
                <div className={field}>
                  <Label htmlFor="category">Insurance category</Label>
                  <Input id="category" name="category" placeholder="e.g. travel" data-testid="upload-category-input" />
                </div>
              </div>
              <div className={field}><Label htmlFor="document_type">Document type</Label><Input id="document_type" name="document_type" defaultValue="wording" data-testid="upload-type-select" /></div>
              <div className={field}><Label htmlFor="product_name">Product name</Label><Input id="product_name" name="product_name" data-testid="upload-product-input" /></div>
            </>
          )}
          <div className={field}><Label htmlFor="source_url">Public source URL (optional)</Label><Input id="source_url" name="source_url" type="url" placeholder="https://…" data-testid="upload-source-url-input" />{isRevision && <p className="text-xs text-slate-500">Enter the URL for this revision. Leave empty if unavailable.</p>}</div>
          <div className="flex items-center gap-2"><input id="review_required" name="review_required" type="checkbox" value="true" className="h-4 w-4 rounded border-slate-300" data-testid="upload-review-checkbox" /><Label htmlFor="review_required">Require review before publication</Label></div>
          <DialogFooter>
            <button type="button" onClick={() => onOpenChange(false)} className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium">Cancel</button>
            <button type="submit" disabled={busy} data-testid="upload-submit-button" className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-slate-300">
              {busy && <Loader2 size={15} className="animate-spin" />} {isRevision ? "Upload revision" : "Upload and queue"}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
