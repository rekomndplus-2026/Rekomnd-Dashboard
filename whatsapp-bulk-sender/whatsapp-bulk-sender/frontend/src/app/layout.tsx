import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { InstanceProvider } from "@/context/InstanceContext";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "WhatsApp Bulk Sender",
  description: "Send WhatsApp messages in bulk securely",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.className} bg-background text-foreground antialiased min-h-screen`}>
        <TooltipProvider>
          <InstanceProvider>
            {children}
            <Toaster position="top-right" richColors theme="dark" />
          </InstanceProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
