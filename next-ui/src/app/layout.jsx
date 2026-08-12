import "./globals.css";
import "./App.css";
import "./LookupPage.css";

export const metadata = {
  title: "Colony PO Dashboard",
  description: "Search and lookup purchase order history and bin inventory",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
