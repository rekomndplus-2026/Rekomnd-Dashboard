"use client";

import { useState, useCallback } from "react";
import { UploadCloud, FileType, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { uploadContactsFile } from "@/lib/api-client";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export function FileUploadZone({ onUploadSuccess }: { onUploadSuccess: (data: any) => void }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragging(true);
    } else if (e.type === "dragleave") {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await handleFile(e.dataTransfer.files[0]);
    }
  }, []);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      await handleFile(e.target.files[0]);
    }
  };

  const handleFile = async (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (ext !== 'csv' && ext !== 'xlsx' && ext !== 'xls') {
      toast.error("Invalid file format. Please upload a CSV or Excel file.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      toast.error("File is too large. Maximum size is 10MB.");
      return;
    }

    setIsUploading(true);
    try {
      const data = await uploadContactsFile(file);
      toast.success(`Successfully uploaded ${data.total_rows} contacts!`);
      onUploadSuccess(data);
    } catch (err: any) {
      toast.error(err.message || "Failed to upload file");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
      className={`relative w-full h-64 border-2 border-dashed rounded-3xl flex flex-col items-center justify-center transition-all duration-300
        ${isDragging ? "border-primary bg-primary/5 scale-[1.02]" : "border-border bg-card/30 hover:border-primary/50"}
        backdrop-blur-sm group
      `}
    >
      <input 
        type="file" 
        accept=".csv,.xlsx,.xls" 
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
        onChange={handleFileChange}
        disabled={isUploading}
      />
      
      {isUploading ? (
        <div className="flex flex-col items-center animate-in fade-in zoom-in duration-300">
          <Loader2 className="w-12 h-12 text-primary animate-spin mb-4" />
          <p className="text-lg font-medium text-foreground">Processing File...</p>
        </div>
      ) : (
        <div className="flex flex-col items-center pointer-events-none transition-transform duration-300 group-hover:-translate-y-2">
          <div className="w-16 h-16 bg-muted/50 rounded-full flex items-center justify-center mb-4 group-hover:bg-primary/10 transition-colors">
            <UploadCloud className={`w-8 h-8 ${isDragging ? "text-primary" : "text-muted-foreground group-hover:text-primary"} transition-colors`} />
          </div>
          <h4 className="text-xl font-bold mb-2">Drag & Drop Contacts File</h4>
          <p className="text-muted-foreground text-sm mb-4">Supports .CSV, .XLSX (Max 10MB)</p>
          <Button variant="secondary" className="pointer-events-none rounded-xl font-semibold">
            Browse Files
          </Button>
        </div>
      )}
    </div>
  );
}
