package roadml.server

import org.http4k.serverless.ApiGatewayV2LambdaFunction
import org.http4k.serverless.AppLoader

/**
 * Lambda に載せるときの入口(API Gateway の HTTP API、ペイロードの形式 2.0)。
 * Lambda のハンドラーには `roadml.server.LambdaHandler::handleRequest` を指定する。
 *
 * SnapStart との関係
 * - このクラスを作るとき(Lambda の初期化)に、設定の読み込み・S3 のクライアント・ルーティングまでを作る。ここまでがスナップショットに入る
 * - PostgreSQL へは、リクエストを受けてから初めてつなぐ(Database)。スナップショットに接続を含めない
 * - マイグレーションとバケットの作成は、ここではしない(デプロイの手順として別に流す)
 * - 一意の値・乱数を初期化中に作らない(スナップショットを戻したすべての実行環境で同じ値になるため)。走行の id はアプリが作る
 */
class LambdaHandler : ApiGatewayV2LambdaFunction(appLoader)

val appLoader = AppLoader { env ->
    val config = Config.load(env)
    createApp(Deps(config, Database(config.db), S3Storage(config)))
}
