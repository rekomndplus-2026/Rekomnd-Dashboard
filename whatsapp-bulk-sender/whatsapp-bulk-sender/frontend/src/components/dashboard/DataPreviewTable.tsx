"use client";

import { useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { previewCleanedContacts } from "@/lib/api-client";
import { toast } from "sonner";
import { Loader2, PhoneCall } from "lucide-react";

export function DataPreviewTable({ fileData, onValidated }: { fileData: any; onValidated: (config: any) => void }) {
  const [phoneColumn, setPhoneColumn] = useState<string>("");
  const [countryCode, setCountryCode] = useState<string>("1");
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<any>(null);

  const columns = fileData?.columns || [];
  const preview = fileData?.preview || [];

  const handleValidate = async () => {
    if (!phoneColumn) {
      toast.error("Please select the column containing phone numbers.");
      return;
    }
    setIsValidating(true);
    try {
      const res = await previewCleanedContacts(fileData.file_id, phoneColumn, countryCode);
      setValidationResult(res);
      toast.success(`Found ${res.valid} valid numbers out of ${res.total}`);
      onValidated({ phoneColumn, countryCode, validCount: res.valid });
    } catch (err: any) {
      toast.error(err.message || "Validation failed");
    } finally {
      setIsValidating(false);
    }
  };

  if (!fileData) return null;

  return (
    <div className="bg-card/40 border border-border/50 backdrop-blur-md p-6 rounded-3xl shadow-xl w-full animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div className="flex items-center gap-3 mb-6">
        <div className="bg-primary/20 p-2 rounded-xl">
          <PhoneCall className="text-primary w-5 h-5" />
        </div>
        <h3 className="text-xl font-bold">Data Mapping</h3>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="space-y-2">
          <Label htmlFor="phone-col" className="text-muted-foreground font-semibold">Phone Number Column</Label>
          <Select value={phoneColumn} onValueChange={(val) => setPhoneColumn(val || "")}>
            <SelectTrigger id="phone-col" className="bg-background/50 h-12 rounded-xl border-border/50">
              <SelectValue placeholder="Select column..." />
            </SelectTrigger>
            <SelectContent>
              {columns.map((col: string) => (
                <SelectItem key={col} value={col}>{col}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        
        <div className="space-y-2">
          <Label htmlFor="country-code" className="text-muted-foreground font-semibold">Default Country Code</Label>
          <div className="relative">
            <span className="absolute left-4 top-3 text-muted-foreground">+</span>
            <input 
              id="country-code"
              type="text" 
              value={countryCode} 
              onChange={(e) => setCountryCode(e.target.value.replace(/\D/g, ''))}
              className="w-full h-12 bg-background/50 border border-border/50 rounded-xl pl-8 pr-4 focus:ring-2 focus:ring-primary focus:outline-none transition-all"
              placeholder="1"
            />
          </div>
        </div>
      </div>

      <div className="mb-6 overflow-x-auto rounded-xl border border-border/30">
        <table className="w-full text-sm text-left">
          <thead className="bg-muted/50 text-muted-foreground uppercase">
            <tr>
              {columns.map((col: string) => (
                <th key={col} className="px-6 py-3 font-medium whitespace-nowrap">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.map((row: any, i: number) => (
              <tr key={i} className="border-b border-border/30 hover:bg-muted/20 transition-colors">
                {columns.map((col: string) => (
                  <td key={col} className="px-6 py-3 whitespace-nowrap text-foreground/80">
                    {row[col]?.toString() || ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex justify-end items-center gap-4">
        {validationResult && (
          <div className="text-sm font-medium">
            <span className="text-green-500">{validationResult.valid} Valid</span>
            <span className="text-muted-foreground mx-2">|</span>
            <span className="text-destructive">{validationResult.invalid} Invalid</span>
          </div>
        )}
        <Button 
          onClick={handleValidate} 
          disabled={isValidating || !phoneColumn}
          className="h-12 px-6 rounded-xl font-semibold shadow-lg shadow-primary/20"
        >
          {isValidating ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Validating...</> : "Validate Data"}
        </Button>
      </div>
    </div>
  );
}
