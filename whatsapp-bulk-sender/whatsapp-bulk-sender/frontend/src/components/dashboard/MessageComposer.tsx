"use client";

import { useState, useRef } from "react";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { MessageSquareText, Send, Image as ImageIcon, X, Loader2 } from "lucide-react";
import { uploadMediaFile } from "@/lib/api-client";

export function MessageComposer({ columns, onSend }: { columns: string[]; onSend: (template: string, mediaFilename?: string) => void }) {
  const [template, setTemplate] = useState("");
  const [mediaFile, setMediaFile] = useState<File | null>(null);
  const [mediaPreview, setMediaPreview] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleMediaSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setMediaFile(file);
      if (file.type.startsWith("image/")) {
        const reader = new FileReader();
        reader.onload = (e) => setMediaPreview(e.target?.result as string);
        reader.readAsDataURL(file);
      } else {
        setMediaPreview(null);
      }
    }
  };

  const removeMedia = () => {
    setMediaFile(null);
    setMediaPreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleSendClick = async () => {
    let mediaFilename: string | undefined;
    if (mediaFile) {
      setIsUploading(true);
      try {
        const result = await uploadMediaFile(mediaFile);
        mediaFilename = result.media_filename;
      } catch (err) {
        alert("Failed to upload media. Please try again.");
        setIsUploading(false);
        return;
      }
      setIsUploading(false);
    }
    onSend(template, mediaFilename);
  };

  const insertVariable = (col: string) => {
    setTemplate(prev => prev + `{${col}}`);
  };

  return (
    <div className="bg-card/40 border border-border/50 backdrop-blur-md p-6 rounded-3xl shadow-xl w-full animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex items-center gap-3 mb-6">
        <div className="bg-primary/20 p-2 rounded-xl">
          <MessageSquareText className="text-primary w-5 h-5" />
        </div>
        <h3 className="text-xl font-bold">Message Template</h3>
      </div>

      <div className="mb-4">
        <Label className="text-muted-foreground font-semibold mb-3 block">Insert Variables</Label>
        <div className="flex flex-wrap gap-2">
          {columns.map((col) => (
            <button
              key={col}
              onClick={() => insertVariable(col)}
              className="text-xs font-mono bg-primary/10 text-primary px-3 py-1.5 rounded-lg hover:bg-primary hover:text-primary-foreground transition-colors border border-primary/20"
            >
              {`{${col}}`}
            </button>
          ))}
        </div>
      </div>

      <div className="relative mb-6">
        <textarea
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          className="w-full h-48 bg-background/50 border border-border/50 rounded-2xl p-4 focus:ring-2 focus:ring-primary focus:outline-none transition-all resize-none font-medium"
          placeholder="Hi {Name}, your order {OrderID} is ready!"
        />
        <div className="absolute bottom-4 right-4 text-xs text-muted-foreground font-mono bg-background/80 px-2 py-1 rounded backdrop-blur-sm">
          {template.length} chars
        </div>
      </div>

      <div className="mb-6 bg-background/50 border border-border/50 rounded-2xl p-4 transition-all">
        <Label className="text-muted-foreground font-semibold mb-3 block">Attach Image/Video (Optional)</Label>
        
        {!mediaFile ? (
          <div 
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed border-primary/30 rounded-xl p-6 flex flex-col items-center justify-center cursor-pointer hover:bg-primary/5 hover:border-primary/50 transition-all text-muted-foreground"
          >
            <ImageIcon className="w-8 h-8 mb-2 opacity-70" />
            <span className="text-sm font-medium">Click to upload media</span>
            <span className="text-xs opacity-60 mt-1">Supports images and MP4 videos</span>
          </div>
        ) : (
          <div className="relative inline-block border border-border rounded-xl p-2 bg-background shadow-sm">
            <button 
              onClick={removeMedia}
              className="absolute -top-2 -right-2 bg-destructive text-destructive-foreground rounded-full p-1 shadow-md hover:scale-110 transition-transform z-10"
            >
              <X className="w-4 h-4" />
            </button>
            {mediaPreview ? (
              <img src={mediaPreview} alt="Preview" className="h-32 object-contain rounded-lg" />
            ) : (
              <div className="h-32 w-48 flex flex-col items-center justify-center bg-muted/50 rounded-lg text-center p-2">
                <ImageIcon className="w-8 h-8 mb-2 opacity-50" />
                <span className="text-xs font-medium truncate w-full">{mediaFile.name}</span>
                <span className="text-[10px] opacity-70">({(mediaFile.size / 1024 / 1024).toFixed(1)} MB)</span>
              </div>
            )}
          </div>
        )}
        <input 
          type="file" 
          ref={fileInputRef} 
          onChange={handleMediaSelect} 
          accept="image/*,video/mp4" 
          className="hidden" 
        />
      </div>

      <div className="flex justify-end">
        <Button 
          onClick={handleSendClick} 
          disabled={!template.trim() || isUploading}
          className="h-12 px-8 rounded-xl font-semibold shadow-lg shadow-primary/20 gap-2 text-lg"
        >
          {isUploading ? (
            <>Uploading Media <Loader2 className="w-5 h-5 animate-spin" /></>
          ) : (
            <>Start Sending <Send className="w-5 h-5" /></>
          )}
        </Button>
      </div>
    </div>
  );
}
