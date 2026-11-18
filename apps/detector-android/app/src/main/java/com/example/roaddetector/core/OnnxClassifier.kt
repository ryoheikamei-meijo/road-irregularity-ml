package com.example.roaddetector.core

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession

/**
 * ONNX Runtime で、core の特徴量から路面のクラス(flat / dansa / dekobo)を判定する。
 *
 * モデルは研究リポジトリの src/experiments/e20261116_export_onnx.py で書き出した core_svm.onnx
 * (StandardScaler + SVM)。入力 features: float32 [N, 5]、出力 label: string [N]、probabilities: float32 [N, 3]
 * (SVM の決定関数の値。確率ではない。列の順番は CLASSES)。
 */
class OnnxClassifier(modelBytes: ByteArray) : AutoCloseable {
    companion object {
        val CLASSES = listOf("dansa", "dekobo", "flat")
        val DISPLAY = mapOf("flat" to "flat", "dansa" to "step", "dekobo" to "rough")
    }

    class Result(val label: String, val scores: FloatArray)

    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val session: OrtSession = OrtSession.SessionOptions().use { opts ->
        opts.setIntraOpNumThreads(1)
        env.createSession(modelBytes, opts)
    }

    fun predict(features: List<DoubleArray>): List<Result> {
        if (features.isEmpty()) return emptyList()
        val input = Array(features.size) { i -> FloatArray(features[i].size) { j -> features[i][j].toFloat() } }
        OnnxTensor.createTensor(env, input).use { tensor ->
            session.run(mapOf("features" to tensor)).use { out ->
                @Suppress("UNCHECKED_CAST")
                val labels = out.get(0).value as Array<String>
                @Suppress("UNCHECKED_CAST")
                val scores = out.get(1).value as Array<FloatArray>
                return labels.indices.map { Result(labels[it], scores[it]) }
            }
        }
    }

    fun predict(features: DoubleArray): Result = predict(listOf(features))[0]

    override fun close() {
        session.close()
    }
}
