"""
ISDB-T エラー訂正・デインターリーブ実装

ISDB-T規格で使用されるエラー訂正技術：
- リードソロモン符号 RS(204,188)
- 畳み込み符号（符号化率1/2, 2/3, 3/4, 5/6, 7/8）
- ビット・バイトデインターリーブ
"""

import logging
import math
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

class ReedSolomonDecoder:
    """
    リードソロモン符号デコーダー RS(204,188)
    
    ISDB-Tで使用されるRS(204,188)符号の復号処理を実装
    - 204シンボル中、188シンボルが情報、16シンボルがパリティ
    - ガロア体GF(2^8)を使用
    """
    
    def __init__(self):
        """RS復号器を初期化"""
        self.n = 204  # 符号長
        self.k = 188  # 情報長
        self.t = 8    # 訂正可能シンボル数 (n-k)/2
        
        # ガロア体GF(2^8)のプリミティブ多項式 x^8 + x^4 + x^3 + x^2 + 1
        self.primitive_poly = 0x11D
        
        # ログテーブルとアンチログテーブルを構築
        self._build_gf_tables()
        
        logger.debug(f"RS({self.n},{self.k})復号器初期化完了")
    
    def _build_gf_tables(self):
        """ガロア体の対数・逆対数テーブルを構築"""
        self.gf_log = [0] * 256
        self.gf_exp = [0] * 512  # 2倍のサイズで循環対応
        
        x = 1
        for i in range(255):
            self.gf_exp[i] = x
            self.gf_log[x] = i
            x <<= 1
            if x & 0x100:
                x ^= self.primitive_poly
        
        # 循環テーブルの拡張
        for i in range(255, 512):
            self.gf_exp[i] = self.gf_exp[i - 255]
        
        self.gf_log[0] = -1  # log(0)は未定義
        
        logger.debug("ガロア体テーブル構築完了")
    
    def gf_mul(self, a: int, b: int) -> int:
        """ガロア体乗算"""
        if a == 0 or b == 0:
            return 0
        return self.gf_exp[self.gf_log[a] + self.gf_log[b]]
    
    def gf_div(self, a: int, b: int) -> int:
        """ガロア体除算"""
        if a == 0:
            return 0
        if b == 0:
            raise ValueError("ガロア体でのゼロ除算")
        return self.gf_exp[self.gf_log[a] - self.gf_log[b] + 255]
    
    def calculate_syndromes(self, received: List[int]) -> List[int]:
        """
        シンドローム計算
        
        Args:
            received: 受信符号語（204バイト）
            
        Returns:
            List[int]: シンドローム（16個）
        """
        syndromes = []
        
        for i in range(16):  # 16個のパリティシンボル
            syndrome = 0
            alpha_power = 1  # α^0 = 1
            
            for j in range(self.n):
                syndrome ^= self.gf_mul(received[j], alpha_power)
                alpha_power = self.gf_mul(alpha_power, self.gf_exp[i + 1])
            
            syndromes.append(syndrome)
        
        return syndromes
    
    def find_error_locator(self, syndromes: List[int]) -> List[int]:
        """
        エラー位置多項式を求める（ベルレカンプ・マッシー算法）
        
        Args:
            syndromes: シンドロームリスト
            
        Returns:
            List[int]: エラー位置多項式の係数
        """
        # 簡略化実装：実際のベルレカンプ・マッシー算法は複雑
        # ここでは基本的なエラー検出のみ実装
        
        error_count = 0
        for syndrome in syndromes:
            if syndrome != 0:
                error_count += 1
                break
        
        if error_count == 0:
            return [1]  # エラーなし
        
        # 簡易的なエラー位置多項式（1つのエラー想定）
        if syndromes[0] != 0:
            return [1, syndromes[0]]
        
        return [1]
    
    def decode(self, received: List[int]) -> Tuple[List[int], bool]:
        """
        リードソロモン復号
        
        Args:
            received: 受信データ（204バイト）
            
        Returns:
            Tuple[List[int], bool]: (復号データ, 復号成功フラグ)
        """
        if len(received) != self.n:
            logger.error(f"RS復号: 不正なデータ長 {len(received)} != {self.n}")
            return received[:self.k], False
        
        # シンドローム計算
        syndromes = self.calculate_syndromes(received)
        
        # エラー検出
        has_error = any(s != 0 for s in syndromes)
        
        if not has_error:
            logger.debug("RS復号: エラーなし")
            return received[:self.k], True
        
        # エラー位置多項式計算
        error_locator = self.find_error_locator(syndromes)
        
        # 簡易的なエラー訂正（1シンボルエラーのみ対応）
        if len(error_locator) == 2:
            # 1つのエラーを訂正
            error_position = self.gf_log[error_locator[1]] if error_locator[1] != 0 else 0
            error_value = syndromes[0]
            
            if 0 <= error_position < len(received):
                corrected = received.copy()
                corrected[error_position] ^= error_value
                logger.debug(f"RS復号: 位置{error_position}のエラーを訂正")
                return corrected[:self.k], True
        
        logger.warning("RS復号: エラー訂正失敗")
        return received[:self.k], False

class ConvolutionalDecoder:
    """
    畳み込み符号デコーダー
    
    ISDB-Tで使用される畳み込み符号の復号処理
    - 制約長: 7
    - 符号化率: 1/2, 2/3, 3/4, 5/6, 7/8
    """
    
    def __init__(self, code_rate: str = "1/2"):
        """
        畳み込み復号器を初期化
        
        Args:
            code_rate: 符号化率（"1/2", "2/3", "3/4", "5/6", "7/8"）
        """
        self.code_rate = code_rate
        self.constraint_length = 7
        self.num_states = 2 ** (self.constraint_length - 1)  # 64状態
        
        # 符号化率に応じたパラメータ設定
        self._setup_code_parameters()
        
        logger.debug(f"畳み込み復号器初期化: 符号化率{code_rate}")
    
    def _setup_code_parameters(self):
        """符号化率に応じたパラメータを設定"""
        if self.code_rate == "1/2":
            self.generator_polynomials = [0o171, 0o133]  # G1, G2
            self.puncture_pattern = None
        elif self.code_rate == "2/3":
            self.generator_polynomials = [0o171, 0o133]
            self.puncture_pattern = [1, 1, 1, 0]  # パンクチャパターン
        elif self.code_rate == "3/4":
            self.generator_polynomials = [0o171, 0o133]
            self.puncture_pattern = [1, 1, 1, 0, 0, 1]
        elif self.code_rate == "5/6":
            self.generator_polynomials = [0o171, 0o133]
            self.puncture_pattern = [1, 1, 1, 0, 0, 1, 1, 0, 0, 1]
        elif self.code_rate == "7/8":
            self.generator_polynomials = [0o171, 0o133]
            self.puncture_pattern = [1, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1]
        else:
            raise ValueError(f"サポートされていない符号化率: {self.code_rate}")
    
    def viterbi_decode(self, received_bits: List[int]) -> List[int]:
        """
        ビタビ復号アルゴリズム
        
        Args:
            received_bits: 受信ビット列
            
        Returns:
            List[int]: 復号ビット列
        """
        if not received_bits:
            return []
        
        # 簡略化されたビタビ復号実装
        # 実際の実装は状態遷移表とパスメトリック計算が必要
        
        # パンクチャされたビットの復元
        if self.puncture_pattern:
            received_bits = self._depuncture(received_bits)
        
        # 硬判定復号（簡易版）
        decoded_bits = []
        for i in range(0, len(received_bits), 2):
            if i + 1 < len(received_bits):
                # 多数決による簡易復号
                bit_sum = received_bits[i] + received_bits[i + 1]
                decoded_bits.append(1 if bit_sum >= 1 else 0)
        
        logger.debug(f"畳み込み復号: {len(received_bits)}ビット → {len(decoded_bits)}ビット")
        return decoded_bits
    
    def _depuncture(self, punctured_bits: List[int]) -> List[int]:
        """パンクチャされたビットを復元"""
        if not self.puncture_pattern:
            return punctured_bits
        
        depunctured = []
        puncture_index = 0
        bit_index = 0
        
        while bit_index < len(punctured_bits):
            pattern_pos = puncture_index % len(self.puncture_pattern)
            
            if self.puncture_pattern[pattern_pos] == 1:
                # 送信されたビット
                if bit_index < len(punctured_bits):
                    depunctured.append(punctured_bits[bit_index])
                    bit_index += 1
                else:
                    depunctured.append(0)  # パディング
            else:
                # パンクチャされたビット（不明ビットとして0を挿入）
                depunctured.append(0)
            
            puncture_index += 1
        
        return depunctured

class BitDeinterleaver:
    """
    ビットデインターリーバー
    
    ISDB-Tで使用されるビットインターリーブの逆処理
    """
    
    def __init__(self, modulation: str = "QPSK"):
        """
        ビットデインターリーバーを初期化
        
        Args:
            modulation: 変調方式（"QPSK", "16QAM", "64QAM"）
        """
        self.modulation = modulation
        
        # 変調方式に応じたパラメータ設定
        if modulation == "QPSK":
            self.bits_per_symbol = 2
        elif modulation == "16QAM":
            self.bits_per_symbol = 4
        elif modulation == "64QAM":
            self.bits_per_symbol = 6
        else:
            raise ValueError(f"サポートされていない変調方式: {modulation}")
        
        logger.debug(f"ビットデインターリーバー初期化: {modulation}")
    
    def deinterleave(self, interleaved_bits: List[int]) -> List[int]:
        """
        ビットデインターリーブ実行
        
        Args:
            interleaved_bits: インターリーブされたビット列
            
        Returns:
            List[int]: デインターリーブされたビット列
        """
        if len(interleaved_bits) % self.bits_per_symbol != 0:
            logger.warning(f"ビット数が変調方式に適合しません: {len(interleaved_bits)} % {self.bits_per_symbol} != 0")
        
        # シンボル数
        num_symbols = len(interleaved_bits) // self.bits_per_symbol
        
        # デインターリーブ実行
        deinterleaved = [0] * len(interleaved_bits)
        
        for symbol_idx in range(num_symbols):
            for bit_idx in range(self.bits_per_symbol):
                # インターリーブパターンの逆変換
                interleaved_pos = symbol_idx * self.bits_per_symbol + bit_idx
                original_pos = self._reverse_interleave_pattern(symbol_idx, bit_idx, num_symbols)
                
                if 0 <= original_pos < len(deinterleaved):
                    deinterleaved[original_pos] = interleaved_bits[interleaved_pos]
        
        logger.debug(f"ビットデインターリーブ完了: {len(interleaved_bits)}ビット")
        return deinterleaved
    
    def _reverse_interleave_pattern(self, symbol_idx: int, bit_idx: int, num_symbols: int) -> int:
        """インターリーブパターンの逆変換"""
        # 簡略化されたインターリーブパターン
        # 実際のISDB-Tでは複雑なパターンが使用される
        
        if self.modulation == "QPSK":
            # QPSKの場合：シンプルなビット順序変更
            new_bit_idx = 1 - bit_idx  # ビット順序を反転
        elif self.modulation == "16QAM":
            # 16QAMの場合：4ビットのローテーション
            rotation_table = [0, 2, 1, 3]
            new_bit_idx = rotation_table[bit_idx]
        elif self.modulation == "64QAM":
            # 64QAMの場合：6ビットの複雑なパターン
            rotation_table = [0, 3, 1, 4, 2, 5]
            new_bit_idx = rotation_table[bit_idx]
        else:
            new_bit_idx = bit_idx
        
        return symbol_idx * self.bits_per_symbol + new_bit_idx

class ByteDeinterleaver:
    """
    バイトデインターリーバー
    
    ISDB-Tで使用されるバイトインターリーブの逆処理
    """
    
    def __init__(self):
        """バイトデインターリーバーを初期化"""
        # ISDB-Tバイトインターリーブパラメータ
        self.convolutional_interleave_depth = 12
        logger.debug("バイトデインターリーバー初期化完了")
    
    def deinterleave(self, interleaved_bytes: List[int]) -> List[int]:
        """
        バイトデインターリーブ実行
        
        Args:
            interleaved_bytes: インターリーブされたバイト列
            
        Returns:
            List[int]: デインターリーブされたバイト列
        """
        if not interleaved_bytes:
            return []
        
        # 畳み込みデインターリーブ（簡略版）
        deinterleaved = []
        delay_lines = [[] for _ in range(self.convolutional_interleave_depth)]
        
        for byte_val in interleaved_bytes:
            # 各遅延線に分散
            line_idx = len(deinterleaved) % self.convolutional_interleave_depth
            delay_lines[line_idx].append(byte_val)
            
            # 最も古いデータから出力
            if delay_lines[line_idx]:
                deinterleaved.append(delay_lines[line_idx].pop(0))
        
        logger.debug(f"バイトデインターリーブ完了: {len(interleaved_bytes)}バイト")
        return deinterleaved

class ErrorCorrectionProcessor:
    """
    エラー訂正処理統合クラス
    
    ISDB-Tのエラー訂正処理を統合的に実行
    """
    
    def __init__(self, modulation: str = "QPSK", code_rate: str = "1/2"):
        """
        エラー訂正処理統合クラスを初期化
        
        Args:
            modulation: 変調方式
            code_rate: 畳み込み符号化率
        """
        self.modulation = modulation
        self.code_rate = code_rate
        
        # 各処理器を初期化
        self.rs_decoder = ReedSolomonDecoder()
        self.conv_decoder = ConvolutionalDecoder(code_rate)
        self.bit_deinterleaver = BitDeinterleaver(modulation)
        self.byte_deinterleaver = ByteDeinterleaver()
        
        logger.info(f"エラー訂正処理初期化: {modulation}, 符号化率{code_rate}")
    
    def process(self, received_bits: List[int]) -> Tuple[List[int], dict]:
        """
        完全なエラー訂正処理パイプライン
        
        Args:
            received_bits: 受信ビット列
            
        Returns:
            Tuple[List[int], dict]: (訂正後データ, 処理統計)
        """
        stats = {
            'input_bits': len(received_bits),
            'bit_deinterleave_success': False,
            'convolutional_decode_success': False,
            'byte_deinterleave_success': False,
            'rs_decode_success': False,
            'output_bytes': 0
        }
        
        logger.debug(f"エラー訂正処理開始: {len(received_bits)}ビット")
        
        try:
            # 1. ビットデインターリーブ
            deinterleaved_bits = self.bit_deinterleaver.deinterleave(received_bits)
            stats['bit_deinterleave_success'] = True
            
            # 2. 畳み込み復号
            decoded_bits = self.conv_decoder.viterbi_decode(deinterleaved_bits)
            stats['convolutional_decode_success'] = True
            
            # 3. ビット列をバイト列に変換
            if len(decoded_bits) % 8 != 0:
                # パディング
                padding = 8 - (len(decoded_bits) % 8)
                decoded_bits.extend([0] * padding)
            
            byte_data = []
            for i in range(0, len(decoded_bits), 8):
                byte_val = 0
                for j in range(8):
                    if i + j < len(decoded_bits):
                        byte_val |= (decoded_bits[i + j] << (7 - j))
                byte_data.append(byte_val)
            
            # 4. バイトデインターリーブ
            deinterleaved_bytes = self.byte_deinterleaver.deinterleave(byte_data)
            stats['byte_deinterleave_success'] = True
            
            # 5. リードソロモン復号（204バイト単位）
            final_data = []
            rs_blocks = len(deinterleaved_bytes) // 204
            
            for block_idx in range(rs_blocks):
                start_pos = block_idx * 204
                end_pos = start_pos + 204
                
                if end_pos <= len(deinterleaved_bytes):
                    rs_block = deinterleaved_bytes[start_pos:end_pos]
                    decoded_block, rs_success = self.rs_decoder.decode(rs_block)
                    final_data.extend(decoded_block)
                    
                    if rs_success:
                        stats['rs_decode_success'] = True
            
            # 余りのデータ処理
            remainder = len(deinterleaved_bytes) % 204
            if remainder > 0:
                final_data.extend(deinterleaved_bytes[-remainder:])
            
            stats['output_bytes'] = len(final_data)
            stats['corrected_data'] = final_data  # 訂正済みデータを統計に追加
            
            logger.info(f"エラー訂正完了: {stats['input_bits']}ビット → {stats['output_bytes']}バイト")
            return final_data, stats
            
        except Exception as e:
            logger.error(f"エラー訂正処理失敗: {e}")
            return [], stats
    
    def get_correction_stats(self) -> dict:
        """エラー訂正統計情報を取得"""
        return {
            'modulation': self.modulation,
            'code_rate': self.code_rate,
            'rs_parameters': f"RS({self.rs_decoder.n},{self.rs_decoder.k})",
            'constraint_length': self.conv_decoder.constraint_length,
            'bits_per_symbol': self.bit_deinterleaver.bits_per_symbol
        }