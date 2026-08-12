"use client";
import { useState, useRef } from "react";
import { bulkLookupParts } from "./api";
import BomResultsTable from "./BomResultsTable";

export default function LookupPage() {
  const [bomText, setBomText] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileInputRef = useRef(null);

  const parseBOM = (text) => {
    // Split by newlines and filter out empty lines
    const lines = text.split('\n').map(line => line.trim()).filter(line => line.length > 0);

    // Extract part numbers - assume each line contains a part number
    // This is a simple implementation - could be enhanced to parse CSV or other formats
    const partNumbers = lines.map(line => {
      // If line contains commas, assume it's CSV and take first column as part number
      if (line.includes(',')) {
        return line.split(',')[0].trim();
      }
      // If line contains tabs, assume it's TSV
      if (line.includes('\t')) {
        return line.split('\t')[0].trim();
      }
      // Otherwise, assume the whole line is a part number
      return line;
    });

    return partNumbers.filter(part => part.length > 0);
  };

  const handleLookup = async () => {
    const textToParse = bomText.trim();
    if (!textToParse) {
      setError("Please enter or upload a BOM first");
      return;
    }

    const partNumbers = parseBOM(textToParse);
    if (partNumbers.length === 0) {
      setError("No valid part numbers found in BOM");
      return;
    }

    if (partNumbers.length > 100) {
      setError("Too many parts (maximum 100). Please reduce the BOM size.");
      return;
    }

    setLoading(true);
    setError(null);
    setRows([]);

    try {
      const data = await bulkLookupParts(partNumbers);
      setRows(data);
    } catch (err) {
      setError(`Lookup failed: ${err.message || "API error"}`);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = (event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      setBomText(e.target.result);
      setError(null);
    };
    reader.onerror = () => {
      setError("Failed to read file");
    };
    reader.readAsText(file);
  };

  const handleSampleBOM = () => {
    const sampleBOM = `ABC123,Widget A,10
DEF456,Gadget B,5
GHI789,Part C,20
JKL012,Component D,15`;
    setBomText(sampleBOM);
    setError(null);
  };

  const clearResults = () => {
    setRows([]);
    setError(null);
  };

  const clearAll = () => {
    setBomText("");
    setRows([]);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="lookup-page">
      <header>
        <div className="header-icon">📋</div>
        <div className="header-text">
          <h1>BOM Lookup</h1>
          <p className="subtitle">Paste or upload a Bill of Materials to get last purchase info for each part</p>
        </div>
      </header>

      <div className="lookup-controls">
        <div className="bom-input-section">
          <label htmlFor="bomText">BOM Input:</label>
          <textarea
            id="bomText"
            placeholder="Paste your BOM here (one part per line, or CSV format)&#10;&#10;Example:&#10;ABC123,Widget A,10&#10;DEF456,Gadget B,5"
            value={bomText}
            onChange={(e) => setBomText(e.target.value)}
            rows={8}
          />
        </div>

        <div className="file-upload">
          <span className="file-upload-help">Or upload a CSV file:</span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.txt"
            onChange={handleFileUpload}
            style={{ display: 'none' }}
          />
          <button
            className="file-upload-btn"
            onClick={() => fileInputRef.current?.click()}
          >
            Choose File
          </button>
        </div>

        <div className="action-buttons">
          <button
            className="sample-btn"
            onClick={handleSampleBOM}
          >
            Load Sample BOM
          </button>

          <button
            className="lookup-btn"
            onClick={handleLookup}
            disabled={loading || !bomText.trim()}
          >
            {loading ? "Looking up parts..." : "Lookup BOM"}
          </button>

          {(rows.length > 0 || error) && (
            <button
              className="clear-btn"
              onClick={clearResults}
            >
              Clear Results
            </button>
          )}

          <button
            className="clear-all-btn"
            onClick={clearAll}
          >
            Clear All
          </button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <BomResultsTable rows={rows} />

      {!loading && bomText.trim() && rows.length === 0 && !error && (
        <p className="no-results">
          No results found for the parts in your BOM
        </p>
      )}
    </div>
  );
}