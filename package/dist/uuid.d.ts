export type CryptoLike = {
    randomUUID?: (() => string) | undefined;
    getRandomValues?: (<T extends Exclude<BufferSource, ArrayBuffer>>(array: T) => T) | undefined;
};
export declare function generateUUID(cryptoLike?: CryptoLike | null): string;
//# sourceMappingURL=uuid.d.ts.map