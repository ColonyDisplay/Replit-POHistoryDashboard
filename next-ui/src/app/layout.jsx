import "./globals.css";
import "./LookupPage.css";
import "./App.css";
import "./Kpi.css";
import "./DataLake.css";

export const metadata = {
  title: "Colony Epicor Dashboard",
  description: "Purchase order, inventory, and published Operations KPI dashboard",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
