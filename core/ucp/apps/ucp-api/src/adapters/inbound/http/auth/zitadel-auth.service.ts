import { Injectable, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import jwt from 'jsonwebtoken';
import jwksClient from 'jwks-rsa';

interface CachedUserinfo {
  data: Record<string, unknown>;
  expiry: number;
}

@Injectable()
export class ZitadelAuthService {
  private jwksClient: jwksClient.JwksClient;
  private userinfoCache: Map<string, CachedUserinfo> = new Map();
  private readonly USERINFO_TTL_MS = 3600000; // 1 hour

  constructor(private readonly configService: ConfigService) {
    const zitadelUrl = this.configService.get<string>('ZITADEL_URL', 'http://ucp.localhost:8080');
    this.jwksClient = jwksClient({
      jwksUri: `${zitadelUrl}/oauth/v2/keys`,
      cache: true,
      rateLimit: true,
    });
  }

  private getKey(header: jwt.JwtHeader, callback: jwt.SigningKeyCallback) {
    this.jwksClient.getSigningKey(header.kid, (err, key) => {
      if (err) return callback(err);
      if (key) {
        const signingKey = key.getPublicKey();
        callback(null, signingKey);
      } else {
        callback(new Error('Key not found'));
      }
    });
  }

  public async verifyToken(token: string): Promise<jwt.JwtPayload> {
    const decodedJwt = jwt.decode(token, { complete: true });

    if (!decodedJwt || !decodedJwt.header || !decodedJwt.header.kid) {
      console.error(
        'ZitadelAuthService: Token is opaque or invalid format. Token length:',
        token.length,
      );
      throw new UnauthorizedException('Invalid JWT token format');
    }

    return new Promise<jwt.JwtPayload>((resolve, reject) => {
      const zitadelUrl = this.configService.get<string>('ZITADEL_URL', 'http://ucp.localhost:8080');
      const audience = this.configService.get<string>('ZITADEL_UCP_PROJECT_ID');
      jwt.verify(
        token,
        this.getKey.bind(this),
        {
          issuer: zitadelUrl,
          audience: audience,
          algorithms: ['RS256'],
        },
        (err, payload) => {
          if (err || !payload || typeof payload === 'string') {
            console.error('JWT Verification failed:', err);
            reject(new UnauthorizedException('Invalid JWT token signature'));
            return;
          }

          const jwtPayload = payload;

          // If roles are missing from the access token, fetch them from the standard OIDC UserInfo endpoint
          if (
            !jwtPayload['urn:zitadel:iam:org:project:roles'] &&
            !jwtPayload[`urn:zitadel:iam:org:project:id:${process.env.ZITADEL_UCP_PROJECT_ID}:roles`]
          ) {
            const jti = jwtPayload['jti'] as string | undefined;
            if (jti) {
              // Check cache first
              const cached = this.userinfoCache.get(jti);
              if (cached && Date.now() < cached.expiry) {
                Object.assign(jwtPayload, cached.data);
                resolve(jwtPayload);
                return;
              }
            }

            const zitadelUrl = this.configService.get<string>(
              'ZITADEL_URL',
              'http://ucp.localhost:8080',
            );
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000);

            fetch(`${zitadelUrl}/oidc/v1/userinfo`, {
              headers: { Authorization: `Bearer ${token}` },
              signal: controller.signal,
            })
              .then((response) => {
                clearTimeout(timeoutId);
                if (response.ok) {
                  return response.json();
                } else {
                  console.error('Failed to fetch userinfo, status:', response.status);
                  return null;
                }
              })
              .then((userinfo: Record<string, unknown> | null) => {
                if (userinfo) {
                  Object.assign(jwtPayload, userinfo);
                  // Cache the result if jti is present
                  if (jti) {
                    this.userinfoCache.set(jti, {
                      data: userinfo,
                      expiry: Date.now() + this.USERINFO_TTL_MS,
                    });
                  }
                }
                resolve(jwtPayload);
              })
              .catch((e) => {
                clearTimeout(timeoutId);
                if (e.name === 'AbortError') {
                  console.error('Userinfo request timed out after 5 seconds');
                } else {
                  console.error('Failed to fetch userinfo request', e);
                }
                resolve(jwtPayload);
              });
          } else {
            resolve(jwtPayload);
          }
        },
      );
    });
  }
}
