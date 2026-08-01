"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AddLeadResponse, api, LeadStatus } from "@/lib/leadmind-api";
import { STATUS_CONFIG } from "@/lib/leadmind-ui";
import { toast } from "sonner";
import { Loader2, Sparkles, Plus } from "lucide-react";

interface AddLeadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLeadAdded: () => void;
}

const SOURCE_OPTIONS = [
  "Website Form",
  "Webinar",
  "Email Campaign",
  "Referral",
  "LinkedIn",
  "Cold Outreach",
  "Demo Request",
  "Newsletter",
];

export function AddLeadDialog({ open, onOpenChange, onLeadAdded }: AddLeadDialogProps) {
  const [name, setName] = useState("");
  const [contactInfo, setContactInfo] = useState("");
  const [message, setMessage] = useState("");
  const [source, setSource] = useState<string>("Website Form");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<AddLeadResponse | null>(null);

  const reset = () => {
    setName("");
    setContactInfo("");
    setMessage("");
    setSource("Website Form");
    setResult(null);
  };

  const handleSubmit = async () => {
    if (!name.trim() || !message.trim()) {
      toast.error("Name and message are required.");
      return;
    }
    setSubmitting(true);
    try {
      const r = await api.addLead({
        name: name.trim(),
        contact_info: contactInfo.trim(),
        message: message.trim(),
        source,
      });
      setResult(r);
      toast.success(`Added ${r.name} → classified as ${r.status}`);
      onLeadAdded();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to add lead");
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = (open: boolean) => {
    if (!open) {
      // Slight delay so the success state is visible before reset
      setTimeout(reset, 200);
    }
    onOpenChange(open);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Plus className="h-4 w-4" />
            Add New Lead
          </DialogTitle>
          <DialogDescription>
            The message will be auto-classified by the AI pipeline (cache → Groq → fallback).
          </DialogDescription>
        </DialogHeader>

        {result ? (
          // Success state
          <div className="space-y-3 py-2">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-4 dark:border-emerald-900 dark:bg-emerald-950/30">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                <span className="text-sm font-medium">
                  Added as{" "}
                  <Badge
                    variant="outline"
                    className={`ml-1 px-1.5 py-0 text-[11px] ${STATUS_CONFIG[result.status as LeadStatus].badgeClass}`}
                  >
                    {result.status}
                  </Badge>
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                {result.classification.reasoning}
              </p>
              <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground">
                <span>Confidence: {(result.classification.confidence * 100).toFixed(0)}%</span>
                <span>·</span>
                <span>Source: {result.classification.source}</span>
                <span>·</span>
                <span>ID: #{result.id}</span>
              </div>
            </div>
          </div>
        ) : (
          // Form state
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="lead-name" className="text-xs">
                  Name <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="lead-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Jane Doe"
                  className="h-9 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="lead-contact" className="text-xs">
                  Contact info
                </Label>
                <Input
                  id="lead-contact"
                  value={contactInfo}
                  onChange={(e) => setContactInfo(e.target.value)}
                  placeholder="jane@example.com"
                  className="h-9 text-sm"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lead-source" className="text-xs">
                Source
              </Label>
              <Select value={source} onValueChange={setSource}>
                <SelectTrigger className="h-9 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SOURCE_OPTIONS.map((s) => (
                    <SelectItem key={s} value={s} className="text-sm">
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lead-message" className="text-xs">
                Message <span className="text-destructive">*</span>
                <span className="ml-2 font-normal text-muted-foreground">
                  (used for AI classification)
                </span>
              </Label>
              <Textarea
                id="lead-message"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="e.g. We urgently need a CRM, budget approved, ready to sign this week."
                className="min-h-[100px] text-sm"
              />
            </div>
          </div>
        )}

        <DialogFooter>
          {result ? (
            <>
              <Button variant="outline" onClick={() => handleClose(false)}>
                Close
              </Button>
              <Button
                onClick={() => {
                  reset();
                }}
                className="gap-1.5"
              >
                <Plus className="h-3.5 w-3.5" />
                Add another
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => handleClose(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={submitting || !name.trim() || !message.trim()}
                className="gap-1.5"
              >
                {submitting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                Add &amp; Classify
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
