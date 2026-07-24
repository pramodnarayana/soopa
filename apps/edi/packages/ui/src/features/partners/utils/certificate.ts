/**
 * Utility functions for parsing and extracting certificate material.
 */

export interface ParsedCertificateMaterial {
  publicCert: string;
  privateKey: string;
}

/**
 * Extracts the public certificate(s) and private key(s) from a combined PEM string.
 * @param pemText The raw text containing one or more PEM blocks.
 * @returns An object containing the extracted public cert and private key (trimmed).
 */
export function extractCertificateMaterial(pemText: string): ParsedCertificateMaterial {
  let publicCert = '';
  let privateKey = '';

  if (!pemText) {
    return { publicCert, privateKey };
  }

  // Extract Public Certificates
  if (pemText.includes('-----BEGIN CERTIFICATE-----')) {
    const match = pemText.match(/-----BEGIN CERTIFICATE-----[^-]+-----END CERTIFICATE-----/g);
    if (match && match.length > 0) {
      publicCert = match.join('\n') + '\n';
    }
  }

  // Extract Private Keys (supports both standard and RSA specific headers)
  if (
    pemText.includes('-----BEGIN PRIVATE KEY-----') ||
    pemText.includes('-----BEGIN RSA PRIVATE KEY-----')
  ) {
    const match = pemText.match(
      /-----BEGIN (?:RSA )?PRIVATE KEY-----[^-]+-----END (?:RSA )?PRIVATE KEY-----/g,
    );
    if (match && match.length > 0) {
      privateKey = match.join('\n') + '\n';
    }
  }

  return {
    publicCert: publicCert.trim(),
    privateKey: privateKey.trim(),
  };
}
