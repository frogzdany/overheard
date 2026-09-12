import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"
import "@copilotkit/react-ui/styles.css"
import { Provider } from "@/components/ui/provider"
import { Chrome } from "@/components/layout/Chrome"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: "Overheard",
  description: "Real-time meeting transcripts, summaries, and questions.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable}`}
    >
      <body>
        <Provider>
          <Chrome>{children}</Chrome>
        </Provider>
      </body>
    </html>
  )
}
